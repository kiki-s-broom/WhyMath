"""WH-1 하네스 shadow 관측 *수확·축적기* — 서버 로그 → verify verdict 분포(오프라인·비노출).

배경 (왜 이 도구가 필요한가)
----------------------------
S1-11(verify 게이트 primary 승격) flip의 전제 ①은 "실 트래픽에서 shadow verify verdict *분포*
확보"다. 그런데 WH-1 shadow 관측(`harness/wh1_shadow.py`)은 `whymath.harness.wh1_shadow.record`
로거에 구조화 JSON 1줄로만 흐르고 **무영속**이다 — 서버 로그에서 그 라인을 골라 모으고,
세션(측정 윈도)을 거듭하며 *축적*할 도구가 없으면 분포는 영영 만들어지지 않는다(도구 공백).
본 모듈이 그 공백을 채운다: 로그 파일(들)에서 record 라인만 파싱 → (옵션) 누적 원장(ndjson)에
중복 제거 append → verdict/턴/status 분포 리포트.

파이프라인 (shadow_measurement_runbook.md "WH-1 verify verdict 수확" 절):
    coach 세션/턴(WHYMATH_WH1_HARNESS_SHADOW_ENABLED=true) → record 로거 JSON(서버 로그 캡처)
    → python -m whymath_backend.harness.wh1_shadow_harvest <로그...> --store ledger.ndjson
    → verdict 분포 검토(사람/별도 게이트 — 본 도구는 판정선 없음)

설계 경계 (정본 패턴 미러)
--------------------------
- **순수 집계 코어**(`parse_log_text`·`dedupe`·`summarize`) + **얇은 CLI**(`main`) —
  `ops/cost_probe.py`·`l4/step_shadow_harvest.py` 구조 미러. HTTP/런타임/DB 경로 0(hermetic).
- **판정선 없음**: 분포 *제시*가 목적이다 — S1-11 flip 판정은 사람/별도 게이트 몫(임의 숫자
  단정 금지·CLAUDE.md "모르면 모른다고"). 종료 코드는 성공/입력 오류만 구분한다.
- **레코드 스키마 단일 진실원천**: 파싱은 emit 측 모델(`Wh1HarnessShadowObservation`·
  `extra="forbid"`)로 검증하고, 로거 이름도 emit 측 `record_logger.name`을 그대로 참조한다
  (문자열 재타이핑 드리프트 차단).

정직 회계 (침묵 실패 금지 — CLAUDE.md)
---------------------------------------
- **parsed / skipped / broken**을 분리 회계한다: record 로거 라인으로 식별됐는데 JSON이
  깨졌으면 broken(예외 *타입명* 로그 — 무타입 경고 금지), record 로거와 무관한 라인(타 로거·
  평문·타 스키마 JSON)은 skipped. 깨진 bare JSON도 broken(로그 로테이션 절단 등 가시화).
- **중복 제거 키 = (dialogue_id, turn_index, observed_at)** — 같은 로그를 두 번 수확해도
  원장이 불어나지 않는다(재실행 멱등). 입력 내 중복도 별도 카운트로 보고한다.
- 원장 내 깨진 라인도 세어 보고한다(원장 부식은 조사 대상이지 조용한 누락 대상이 아니다).
- **전이별 집계는 신판/구판 분리 회계(S3-07)** — 전이 카운트(n_correct 등)를 보유한 레코드만
  Σ에 합산하고, 구판(카운트 필드 없음·파싱은 하위호환으로 성공)은 별도 건수로 표기한다.
  구판을 '전이 0'으로 합산하면 분포가 위조된다(0 위장 금지).

- **primary 채택률(OPS-134 ②)은 분포와 분모를 섞지 않는다** — 하네스가 결과 없이 중단된 턴
  (`status="aborted"`·타임아웃/예외)은 verdict가 없고 전이 카운트도 없어, 기존 분포에 섞으면
  "verify 미호출 턴"과 "구판 레코드"로 오집계된다. 그래서 기존 분포(verdict·전이·형태·status)는
  정상 완료 턴만으로 계산해 **변경 전과 같은 값**을 유지하고, 중단 턴은 채택률 절에서만 센다.
  채택률의 분모는 결말(`primary_outcome`)을 기록한 primary 시도뿐이며, 결말이 없는 구판 primary
  레코드는 분모에서 빼고 따로 센다 — 구판을 채택으로 세면 기록이 0줄이던 폴백이 사라진 채
  비율이 위조된다.

프라이버시: 관측 레코드 자체가 비식별(status·action_type·verdict·카운트·id뿐 — 학생 원문·풀이
단계·발화 원문·정답 없음·`wh1_shadow.py` 규약)이므로 원장·리포트도 비식별이다.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, get_args

from pydantic import BaseModel, ConfigDict

from whymath_backend.harness.wh1_shadow import (
    PRIMARY_ADOPTED,
    PrimaryOutcome,
    Wh1HarnessShadowObservation,
    record_logger,
)

__all__ = [
    "PRIMARY_OUTCOME_LABELS",
    "RECORD_LOGGER_NAME",
    "VERIFY_TARGET_LABELS",
    "DurationSummary",
    "ParseAccounting",
    "Wh1ShadowDistributionSummary",
    "Wh1ShadowHarvestReport",
    "dedup_key",
    "dedupe",
    "filter_window",
    "harvest_files",
    "load_ledger",
    "main",
    "parse_log_text",
    "render_report",
    "summarize",
]

logger = logging.getLogger(__name__)

# emit 측 로거 이름을 그대로 참조 — 문자열 재타이핑으로 인한 이름 드리프트를 구조적으로 차단.
RECORD_LOGGER_NAME: str = record_logger.name

# verdict 4-라벨(3-state + verify 미호출 None) — 분포 리포트의 고정 축(0건이어도 표기).
_VERDICT_LABELS: tuple[str, ...] = ("correct", "incorrect", "unverifiable", "none")

# **판정 모집단** — verify가 실제로 호출된 턴(3-state)만. `none`(verify 미호출 대화 턴)은
# 사전등록 판정문(s3_pilot_briefing.md 트리거 ③ 모집단 정의)에서 분모 밖이라 분리한다.
# 리포트 상단의 4-라벨 비율은 *전체* 분모라 그대로 읽으면 사전등록 비율과 다른 수가 된다 —
# 그 오독을 막기 위해 같은 리포트에 모집단 분모를 병기한다(판정선은 여전히 내지 않는다).
VERIFY_TARGET_LABELS: tuple[str, ...] = ("correct", "incorrect", "unverifiable")

# primary 결말 라벨 전체 — 방출 측 닫힌 어휘(`PrimaryOutcome`)에서 그대로 유도한다(재타이핑 드리프트
# 차단). 0건이어도 표기하는 고정 축이라 "그 사유가 한 번도 안 났다"와 "사유 집계가 없다"가
# 구분된다.
PRIMARY_OUTCOME_LABELS: tuple[str, ...] = get_args(PrimaryOutcome)

# 하네스가 결과 없이 중단된 턴의 status(OPS-134 ②) — 기존 verdict/전이 분포의 분모에서 뺀다.
_ABORTED_STATUS = "aborted"

# 종료 코드 — 판정선이 아니라 도구 성공/입력 오류 구분(cost_probe CLI 관례의 절반만 차용).
_EXIT_OK = 0
_EXIT_ERROR = 2


def _verdict_label(verdict: str | None) -> str:
    """verify_verdict(3-state|None) → 리포트 라벨. None은 'none'(verify 미호출)로 표기."""
    return "none" if verdict is None else verdict


class ParseAccounting(BaseModel):
    """로그 파싱 정직 회계 — 성공/비해당/깨짐을 분리해 '조용한 누락'을 구조적으로 막는다."""

    model_config = ConfigDict(extra="forbid")

    lines_total: int
    """비어 있지 않은 입력 라인 총수(빈 줄 제외)."""

    parsed: int
    """`Wh1HarnessShadowObservation`으로 검증 통과한 record 라인 수."""

    skipped: int
    """record 로거와 무관한 비해당 라인 수(타 로거·평문·타 스키마 JSON)."""

    broken: int
    """record 라인으로 식별됐으나 JSON이 깨진(또는 bare JSON 절단) 라인 수 — 조사 대상."""


def parse_log_text(text: str) -> tuple[list[Wh1HarnessShadowObservation], ParseAccounting]:
    """서버 로그 텍스트에서 record 라인만 골라 관측으로 파싱 — 순수·정직 회계.

    라인 분류(우선순위 순):
      ① 라인에 record 로거 이름(`RECORD_LOGGER_NAME`)이 있으면 *record 라인*이다 — 로거 이름
         뒤 첫 `{`부터 라인 끝까지를 JSON으로 검증한다(핸들러 포맷 prefix — 타임스탬프·레벨 —
         무관). 검증 실패는 **broken**(예외 타입명 로그 — 침묵 실패 금지·라인 원문은 로그에
         안 담는다).
      ② 로거 이름 없이 `{`로 시작하는 라인(순수 JSONL 캡처·runbook 로그 파이프라인 산출):
         JSON 자체가 깨지면 **broken**(로테이션 절단 가시화), JSON은 유효하나 우리 스키마가
         아니면 **skipped**(타 로거의 JSON 레코드 — `extra="forbid"`가 오귀속 차단).
      ③ 그 밖의 라인(uvicorn access·평문 로그 등)은 **skipped**.

    빈 줄은 회계에 넣지 않는다(라인이 아니라 공백). 반환 순서는 입력 순서를 보존한다.
    """
    observations: list[Wh1HarnessShadowObservation] = []
    lines_total = parsed = skipped = broken = 0
    for line_num, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        lines_total += 1
        marker = stripped.find(RECORD_LOGGER_NAME)
        if marker >= 0:
            # record 라인 — 로거 이름 뒤 첫 '{'부터가 emit 페이로드(model_dump_json 1줄).
            start = stripped.find("{", marker + len(RECORD_LOGGER_NAME))
            payload = stripped[start:] if start >= 0 else ""
            try:
                observations.append(Wh1HarnessShadowObservation.model_validate_json(payload))
                parsed += 1
            except Exception as exc:  # noqa: BLE001 — 회계로 흡수하되 타입명은 반드시 로그
                broken += 1
                logger.warning(
                    "record 라인 파싱 실패(%s) — broken 회계(line %d)",
                    type(exc).__name__,
                    line_num,
                )
            continue
        if stripped.startswith("{"):
            # bare JSON 라인 — 순수 JSONL 캡처 경로. 깨짐(절단)과 타 스키마를 구분 회계.
            try:
                json.loads(stripped)
            except json.JSONDecodeError as exc:
                broken += 1
                logger.warning(
                    "bare JSON 라인 깨짐(%s) — broken 회계(line %d·로테이션 절단 의심)",
                    type(exc).__name__,
                    line_num,
                )
                continue
            try:
                observations.append(Wh1HarnessShadowObservation.model_validate_json(stripped))
                parsed += 1
            except Exception:  # noqa: BLE001 — 유효 JSON이나 타 스키마 = 비해당(오귀속 차단)
                skipped += 1
            continue
        skipped += 1  # 평문·타 로거 라인 — 비해당.
    return observations, ParseAccounting(
        lines_total=lines_total, parsed=parsed, skipped=skipped, broken=broken
    )


# 중복 제거 키 — 관측의 자연 키. create_session 관측은 dialogue_id=None·turn_index=1이라
# observed_at(µs 해상도 UTC)이 사실상 유일성을 담보한다.
DedupKey = tuple[str | None, int, str]


def dedup_key(obs: Wh1HarnessShadowObservation) -> DedupKey:
    """관측 1건의 중복 제거 키 = (dialogue_id, turn_index, observed_at ISO)."""
    return (obs.dialogue_id, obs.turn_index, obs.observed_at.isoformat())


def dedupe(
    observations: Iterable[Wh1HarnessShadowObservation],
    *,
    seen: set[DedupKey] | None = None,
) -> tuple[list[Wh1HarnessShadowObservation], int]:
    """관측 스트림을 키 기준으로 유일화 — (유일 관측 순서보존 리스트, 걸러진 중복 수).

    `seen`을 주면 그 키 집합에 이미 있는 관측도 중복으로 거른다(원장 대비 신규분 산출).
    집합은 *제자리 갱신*된다 — 호출자가 원장 키를 넘겨 신규 키가 누적되게(단일 패스).
    """
    keys = seen if seen is not None else set()
    unique: list[Wh1HarnessShadowObservation] = []
    duplicates = 0
    for obs in observations:
        key = dedup_key(obs)
        if key in keys:
            duplicates += 1
            continue
        keys.add(key)
        unique.append(obs)
    return unique, duplicates


def _as_utc(moment: datetime) -> datetime:
    """시간대 미표기(naive) 시각을 UTC로 간주 — 비교 시 TypeError를 내지 않기 위한 정규화.

    관측 emit은 항상 tz-aware UTC(`wh1_shadow.py` default_factory)라 정상 경로에서는 no-op이다.
    수기 편집·외부 도구가 naive 값을 넣은 원장에서도 구간 비교가 *조용히 터지지 않게* 한다
    (해석 규칙은 CLI 출력에 명시 — 숨은 가정 금지).
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def filter_window(
    observations: Sequence[Wh1HarnessShadowObservation],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[Wh1HarnessShadowObservation], int]:
    """관측 시각 구간으로 **집계 대상**을 자른다 — (구간 내 관측, 구간 밖으로 제외된 수).

    경계는 `since <= observed_at <= until`(양끝 포함). 둘 다 None이면 no-op(원본·0).

    왜 필요한가: 원장은 *축적*이 목적이라 수확 리포트가 항상 원장 전체 분포를 낸다. 그래서
    측정 회차 하나를 판정하려 하면 **이전 회차(합성 probe 포함)가 같은 분모에 남는다** —
    2026-07-19 합성 60제출(eq 24/24 correct)이 그대로 섞이면 이번 회차와 무관하게 통과가
    나온다(거짓 green). 필터는 원장을 건드리지 않고 *보는 창*만 자른다(축적 불변·재현 가능).
    """
    if since is None and until is None:
        return list(observations), 0
    kept: list[Wh1HarnessShadowObservation] = []
    excluded = 0
    for obs in observations:
        moment = _as_utc(obs.observed_at)
        if since is not None and moment < _as_utc(since):
            excluded += 1
            continue
        if until is not None and moment > _as_utc(until):
            excluded += 1
            continue
        kept.append(obs)
    return kept, excluded


def load_ledger(path: Path) -> tuple[list[Wh1HarnessShadowObservation], int]:
    """누적 원장(ndjson·한 줄당 관측 JSON) 로드 — (관측 리스트, 깨진 라인 수).

    원장 부재는 (빈 리스트, 0) — 첫 축적. 깨진 라인은 세어 보고하고 건너뛴다(예외 타입명
    로그 — 원장 부식을 조용히 덮지 않되, 부식 1줄이 축적 전체를 막지도 않는다).
    """
    if not path.exists():
        return [], 0
    observations: list[Wh1HarnessShadowObservation] = []
    broken = 0
    for line_num, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            observations.append(Wh1HarnessShadowObservation.model_validate_json(stripped))
        except Exception as exc:  # noqa: BLE001 — 부식 라인 회계·타입명 로그(침묵 실패 금지)
            broken += 1
            logger.warning(
                "원장 라인 파싱 실패(%s) — 건너뜀(line %d·원장 부식 조사 대상)",
                type(exc).__name__,
                line_num,
            )
    return observations, broken


def _append_ledger(path: Path, observations: Sequence[Wh1HarnessShadowObservation]) -> None:
    """신규 관측을 원장에 append(ndjson·정규화된 model_dump_json 1줄씩)."""
    if not observations:
        return
    with path.open("a", encoding="utf-8") as fh:
        for obs in observations:
            fh.write(obs.model_dump_json() + "\n")


class DurationSummary(BaseModel):
    """소요 시간(ms) 분포 요약 — 최근접 순위(nearest-rank) 백분위. 표본이 작으면 `n`도 읽는다."""

    model_config = ConfigDict(extra="forbid")

    n: int
    p50: int
    p90: int
    max: int


def _duration_summary(values: Sequence[int]) -> DurationSummary | None:
    """값이 없으면 None — 표본 0을 0ms로 위장하지 않는다."""
    if not values:
        return None
    ordered = sorted(values)

    def pick(q: float) -> int:
        return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]

    return DurationSummary(n=len(ordered), p50=pick(0.5), p90=pick(0.9), max=ordered[-1])


class Wh1ShadowDistributionSummary(BaseModel):
    """verdict 분포 요약 — S1-11 flip 전제 ①의 결정 변수(판정선 없음·분포 제시)."""

    model_config = ConfigDict(extra="forbid")

    total: int
    """집계 대상 관측 총건수(중복 제거 후)."""

    verdict_counts: dict[str, int]
    """verify_verdict 분포 — correct/incorrect/unverifiable/none(verify 미호출) 각 건수."""

    verdict_ratios: dict[str, float]
    """verdict 라벨별 비율(분모=total). total=0이면 빈 dict — 0%로 위장하지 않는다(날조 금지)."""

    status_counts: dict[str, int]
    """하네스 턴 종료 status(ended|budget_exhausted) 분포."""

    turn_verdicts: dict[int, dict[str, int]]
    """turn_index별 verdict 분포 — 세션 내 verdict 추이 관측(S1-11 근거·키 오름차순)."""

    transition_counts: dict[str, int]
    """턴당 *전이별* verify 판정 합산(Σn_correct/Σn_incorrect/Σn_unverifiable·S3-07) — 카운트
    보유(신판) 레코드만 합산한다. 마지막 판정 축(verdict_counts)이 가리는 앞 전이의 correct를
    분포에 보이게 하는 추가 축(2026-07-19 실측 왜곡)·기존 verdict 축 의미는 불변."""

    transition_records: int
    """전이 카운트를 보유한 레코드 수(신판·S3-07+) — transition_counts 합산의 표본 회계."""

    verify_target_total: int
    """**판정 모집단** 크기 = verdict가 3-state인 턴 수(none=verify 미호출 제외·사전등록 정의).

    사전등록 판정문(트리거 ③)의 분모다. 리포트 상단 4-라벨 비율은 `total`(none 포함) 분모라
    이 수와 다르다 — 두 분모를 같은 화면에 병기해 오독을 구조적으로 막는다."""

    verify_target_ratios: dict[str, float]
    """판정 모집단 분모 기준 3-state 비율. 모집단 0이면 빈 dict(0%로 위장 금지)."""

    form_transition_counts: dict[str, int]
    """전이 *형태*별 합산(Σ등호 방정식·Σ혼합 형태·S3-51) — 형태 축 보유 레코드만 합산."""

    equation_turns: int
    """등호 방정식 전이가 **1건 이상**인 턴 수 — 사전등록 유효성 전제 V3가 읽는 수다."""

    form_records: int
    """형태 축(n_equation_transitions)을 보유한 레코드 수(신판·S3-51+) — 합산의 표본 회계."""

    form_legacy_records: int
    """형태 축 미보유 레코드 수(S3-51 이전) — 합산 제외·분리 표기(0으로 위장 금지)."""

    legacy_records: int
    """전이 카운트 미보유 레코드 수(구판·S3-07 이전) — 합산에서 제외하고 분리 표기한다
    (구판을 '전이 0'으로 위장 금지 — 정직 회계)."""

    distinct_dialogues: int
    """dialogue_id가 있는 관측의 고유 dialogue 수(None 제외 — create 관측은 id 미탑재)."""

    observed_at_min: datetime | None
    """가장 이른 관측 시각(관측 0건이면 None)."""

    observed_at_max: datetime | None
    """가장 늦은 관측 시각(관측 0건이면 None)."""

    aborted_total: int = 0
    """하네스가 결과 없이 중단된 턴 수(`status="aborted"`·타임아웃/예외·OPS-134 ②).

    위 `total`과 모든 verdict/전이/형태/status 분포에는 **들어 있지 않다** — 그 분포는 정상 완료
    턴의 것이고 변경 전과 같은 값이다. 중단 턴은 채택률 축(아래 `primary_*`)에서만 센다."""

    primary_attempts: int = 0
    """결말(`primary_outcome`)을 기록한 primary 시도 수 — **채택률의 분모**."""

    primary_legacy_records: int = 0
    """`primary=True`인데 결말 미기록인 구판 레코드 수 — 분모에서 빼고 따로 센다(0 위장 금지).
    이 수가 0보다 크면 채택률은 결말 계측 이후 구간만의 값이다."""

    primary_outcome_counts: dict[str, int] = {}
    """결말 라벨별 건수 — 전 라벨을 0건이어도 담는다(시도 0건이면 빈 dict)."""

    primary_adopted: int = 0
    """결말이 `adopted`(하네스 발화 채택)인 시도 수 — **채택률의 분자**."""

    primary_adoption_rate: float | None = None
    """채택률 = 채택 / 시도. **시도 0건이면 None** — 0%가 아니라 "분모 없음"이다."""

    elapsed_ms_adopted: DurationSummary | None = None
    """채택된 턴의 소요(ms) 분포. 소요 기록 턴이 없으면 None."""

    elapsed_ms_fallback: DurationSummary | None = None
    """폴백된 턴(채택 외 전부)의 소요(ms) 분포. 타임아웃 턴은 예산 부근에 몰린다."""

    llm_calls_accounted: int = 0
    """LLM 호출 수를 기록한 시도 수 — 아래 호출 합계의 표본 회계(미기록 시도는 합산에서 빠진다)."""

    llm_calls_in_adopted: int = 0
    """채택된 턴이 시작한 LLM 호출 합."""

    llm_calls_in_fallback: int = 0
    """**폴백된 턴이 시작한 LLM 호출 합 — 출력이 학생에게 닿지 않은 호출**(OPS-134 ③). 이 호출은
    Langfuse에 `traffic_surface=serving`으로 이미 전송됐으므로 학생 대면 비용 표본에 들어 있다."""

    fallback_llm_call_share: float | None = None
    """전체 LLM 호출 중 폴백된 턴이 쓴 비중 = fallback / (adopted + fallback). 호출 합 0이면 None.
    게이트② 표본이 "출력이 버려진 호출"로 얼마나 채워져 있는지의 인프로세스 근사다."""

    timeout_turns: int = 0
    """결말이 `fallback_timeout`인 시도 수."""

    timeout_elapsed_ms_total: int = 0
    """타임아웃 턴 중 소요와 LLM 합을 **둘 다** 기록한 턴의 소요 합(ms)."""

    timeout_llm_ms_total: int = 0
    """같은 턴들의 끝난 LLM 호출 소요 합(ms). 소요 합에서 이 값을 뺀 나머지는 "취소된 호출 + 비LLM
    단계(후보 조립·캐시 대기·도구 실행)"이며 이 둘은 서버 로그만으로 갈리지 않는다(①의 한계)."""

    timeout_inflight_calls: int = 0
    """타임아웃 턴에서 취소 시점에 비행 중이던 호출 수(시작 − 끝남)."""


def summarize(
    observations: Sequence[Wh1HarnessShadowObservation],
) -> Wh1ShadowDistributionSummary:
    """관측 리스트 → verdict/턴/status 분포 요약(순수·결정론·판정선 없음).

    기존 분포(verdict·전이·형태·status)는 **정상 완료 턴만**으로 계산한다 — 중단 턴(`aborted`)은
    하네스 결과가 없어 그 분포의 어느 칸에도 속하지 않는다(모듈 docstring). 채택률 축은 중단 턴을
    포함한 전체 primary 시도를 본다.
    """
    completed = [obs for obs in observations if obs.status != _ABORTED_STATUS]
    aborted = [obs for obs in observations if obs.status == _ABORTED_STATUS]
    total = len(completed)
    verdict_counts: dict[str, int] = {label: 0 for label in _VERDICT_LABELS}
    status_counts: dict[str, int] = {}
    turn_verdicts: dict[int, dict[str, int]] = {}
    transition_counts: dict[str, int] = {"correct": 0, "incorrect": 0, "unverifiable": 0}
    transition_records = 0
    legacy_records = 0
    form_counts: dict[str, int] = {"equation": 0, "mixed": 0}
    equation_turns = 0
    form_records = 0
    form_legacy_records = 0
    dialogues: set[str] = set()
    observed_min: datetime | None = None
    observed_max: datetime | None = None
    for obs in completed:
        label = _verdict_label(obs.verify_verdict)
        verdict_counts[label] = verdict_counts.get(label, 0) + 1
        status_counts[obs.status] = status_counts.get(obs.status, 0) + 1
        per_turn = turn_verdicts.setdefault(obs.turn_index, {})
        per_turn[label] = per_turn.get(label, 0) + 1
        # 전이별 집계(S3-07) — 카운트 3종을 모두 보유한 신판만 합산한다. 하나라도 None이면
        # 구판(카운트 미기록)으로 분리 회계 — 구판을 '전이 0'으로 위장하지 않는다(정직 회계).
        if (
            obs.n_correct is not None
            and obs.n_incorrect is not None
            and obs.n_unverifiable is not None
        ):
            transition_records += 1
            transition_counts["correct"] += obs.n_correct
            transition_counts["incorrect"] += obs.n_incorrect
            transition_counts["unverifiable"] += obs.n_unverifiable
        else:
            legacy_records += 1
        # 형태 축(S3-51) — 구판(필드 None)은 합산에서 빼고 따로 센다(전이 카운트 선례 동형).
        if obs.n_equation_transitions is None:
            form_legacy_records += 1
        else:
            form_records += 1
            form_counts["equation"] += obs.n_equation_transitions
            form_counts["mixed"] += obs.n_mixed_form_transitions or 0
            if obs.n_equation_transitions > 0:
                equation_turns += 1
        if obs.dialogue_id is not None:
            dialogues.add(obs.dialogue_id)
        if observed_min is None or obs.observed_at < observed_min:
            observed_min = obs.observed_at
        if observed_max is None or obs.observed_at > observed_max:
            observed_max = obs.observed_at
    # 중단 턴도 시각 범위·고유 dialogue에는 든다 — 관측 창과 세션 수는 "무슨 일이 있었나"의 축이라
    # 하네스가 끝까지 돌았는지와 무관하다.
    for obs in aborted:
        if obs.dialogue_id is not None:
            dialogues.add(obs.dialogue_id)
        if observed_min is None or obs.observed_at < observed_min:
            observed_min = obs.observed_at
        if observed_max is None or obs.observed_at > observed_max:
            observed_max = obs.observed_at
    # 비율은 total>0일 때만 — 표본 0을 0%로 위장하지 않는다(cost_probe '미상' 관례).
    verdict_ratios = (
        {label: count / total for label, count in verdict_counts.items()} if total > 0 else {}
    )
    # 판정 모집단(none 제외) — 사전등록 판정문의 분모. 같은 규칙으로 0이면 빈 dict.
    verify_target_total = sum(verdict_counts.get(label, 0) for label in VERIFY_TARGET_LABELS)
    verify_target_ratios = (
        {
            label: verdict_counts.get(label, 0) / verify_target_total
            for label in VERIFY_TARGET_LABELS
        }
        if verify_target_total > 0
        else {}
    )
    return Wh1ShadowDistributionSummary(
        total=total,
        verdict_counts=verdict_counts,
        verdict_ratios=verdict_ratios,
        status_counts=dict(sorted(status_counts.items())),
        turn_verdicts={k: turn_verdicts[k] for k in sorted(turn_verdicts)},
        transition_counts=transition_counts,
        transition_records=transition_records,
        verify_target_total=verify_target_total,
        verify_target_ratios=verify_target_ratios,
        form_transition_counts=form_counts,
        equation_turns=equation_turns,
        form_records=form_records,
        form_legacy_records=form_legacy_records,
        legacy_records=legacy_records,
        distinct_dialogues=len(dialogues),
        observed_at_min=observed_min,
        observed_at_max=observed_max,
        aborted_total=len(aborted),
        **_primary_accounting(observations),
    )


class _PrimaryAccounting(TypedDict, total=False):
    """`_primary_accounting`의 반환 — 요약 모델의 같은 이름 필드로 펼쳐진다(키별 타입 고정)."""

    primary_attempts: int
    primary_legacy_records: int
    primary_outcome_counts: dict[str, int]
    primary_adopted: int
    primary_adoption_rate: float | None
    elapsed_ms_adopted: DurationSummary | None
    elapsed_ms_fallback: DurationSummary | None
    llm_calls_accounted: int
    llm_calls_in_adopted: int
    llm_calls_in_fallback: int
    fallback_llm_call_share: float | None
    timeout_turns: int
    timeout_elapsed_ms_total: int
    timeout_llm_ms_total: int
    timeout_inflight_calls: int


def _primary_accounting(observations: Sequence[Wh1HarnessShadowObservation]) -> _PrimaryAccounting:
    """primary 채택률·소요·폐기 호출 비중(OPS-134 ②③①) — 중단 턴을 포함한 전체 primary 시도 기준.

    분모는 **결말을 기록한 primary 시도**다. 결말이 없는 구판 primary 레코드는 분모에서 빼고
    `primary_legacy_records`로 따로 센다. shadow(비노출) 레코드는 학생에게 서빙된 턴이 아니므로
    채택률과 무관하다. 시도 0건이면 비율은 None이다(0% 위장 금지).
    """
    attempts = [o for o in observations if o.primary and o.primary_outcome is not None]
    legacy = sum(1 for o in observations if o.primary and o.primary_outcome is None)
    if not attempts:
        return {"primary_legacy_records": legacy}
    counts: dict[str, int] = {label: 0 for label in PRIMARY_OUTCOME_LABELS}
    for o in attempts:
        outcome = o.primary_outcome
        if outcome is not None:  # attempts 필터가 보장하지만 타입을 좁혀 둔다.
            counts[outcome] += 1
    adopted = counts[PRIMARY_ADOPTED]

    adopted_obs = [o for o in attempts if o.primary_outcome == PRIMARY_ADOPTED]
    fallback_obs = [o for o in attempts if o.primary_outcome != PRIMARY_ADOPTED]
    calls_adopted = [o.llm_calls for o in adopted_obs if o.llm_calls is not None]
    calls_fallback = [o.llm_calls for o in fallback_obs if o.llm_calls is not None]
    total_calls = sum(calls_adopted) + sum(calls_fallback)

    timeout_obs = [
        o
        for o in attempts
        if o.primary_outcome == "fallback_timeout"
        and o.elapsed_ms is not None
        and o.llm_ms_total is not None
    ]
    return {
        "primary_attempts": len(attempts),
        "primary_legacy_records": legacy,
        "primary_outcome_counts": counts,
        "primary_adopted": adopted,
        "primary_adoption_rate": adopted / len(attempts),
        "elapsed_ms_adopted": _duration_summary(
            [o.elapsed_ms for o in adopted_obs if o.elapsed_ms is not None]
        ),
        "elapsed_ms_fallback": _duration_summary(
            [o.elapsed_ms for o in fallback_obs if o.elapsed_ms is not None]
        ),
        "llm_calls_accounted": len(calls_adopted) + len(calls_fallback),
        "llm_calls_in_adopted": sum(calls_adopted),
        "llm_calls_in_fallback": sum(calls_fallback),
        "fallback_llm_call_share": (sum(calls_fallback) / total_calls if total_calls > 0 else None),
        "timeout_turns": counts["fallback_timeout"],
        "timeout_elapsed_ms_total": sum(o.elapsed_ms or 0 for o in timeout_obs),
        "timeout_llm_ms_total": sum(o.llm_ms_total or 0 for o in timeout_obs),
        "timeout_inflight_calls": sum(
            (o.llm_calls or 0) - (o.llm_calls_finished or 0)
            for o in attempts
            if o.primary_outcome == "fallback_timeout"
        ),
    }


class Wh1ShadowHarvestReport(BaseModel):
    """수확 1회의 전체 리포트 — 파싱 회계 + 원장 회계 + 분포 요약(--json 직렬화 대상)."""

    model_config = ConfigDict(extra="forbid")

    sources: list[str]
    """입력 로그 파일 경로(들)."""

    accounting: ParseAccounting
    """입력 파싱 정직 회계(parsed/skipped/broken)."""

    input_duplicates: int
    """입력 내부·원장 대비 중복으로 걸러진 관측 수(멱등 재수확 가시화)."""

    store_path: str | None
    """누적 원장 경로(--store). None이면 이번 입력만 집계(무축적)."""

    ledger_existing: int
    """append 전 원장에 이미 있던 유일 관측 수."""

    ledger_broken: int
    """원장에서 파싱 불가였던 라인 수(부식 조사 대상)."""

    appended: int
    """이번 수확으로 원장에 새로 append된 관측 수."""

    filter_since: str | None
    """집계 구간 시작(--since·ISO·포함). None이면 하한 없음."""

    filter_until: str | None
    """집계 구간 끝(--until·ISO·포함). None이면 상한 없음."""

    filtered_out: int
    """구간 밖이라 **집계에서 제외**된 관측 수(원장에는 그대로 남아 있다).

    0이 아니면 이 리포트의 분포는 원장 전체가 아니라 *구간 표본*이다 — 그 사실이 리포트
    본문에도 한 줄로 찍힌다(무엇을 보고 있는지 숨기지 않는다)."""

    summary: Wh1ShadowDistributionSummary
    """분포 요약 — 원장 사용 시 *원장 전체* 기준, 미사용 시 이번 입력(중복 제거) 기준."""


def harvest_files(
    paths: Sequence[Path],
    *,
    store: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Wh1ShadowHarvestReport:
    """로그 파일(들) 수확 → (옵션) 원장 축적 → 분포 리포트 — CLI 본체(파일 I/O 최소).

    원장(`store`) 사용 시: 원장 로드(자체 dedup) → 입력에서 원장에 없는 신규만 append →
    **원장 전체**(기존+신규) 기준으로 분포 산출 — 여러 세션(측정 윈도)에 걸친 축적이 목적이다.
    미사용 시: 이번 입력(중복 제거)만 집계한다. 입력 파일 부재·읽기 실패(OSError)는 그대로
    던진다 — `main`이 잡아 명확한 오류로 보고한다(부분 수확을 조용히 리포트로 위장하지 않음).
    """
    observations: list[Wh1HarnessShadowObservation] = []
    lines_total = parsed = skipped = broken = 0
    for path in paths:
        parsed_obs, acct = parse_log_text(path.read_text(encoding="utf-8"))
        observations.extend(parsed_obs)
        lines_total += acct.lines_total
        parsed += acct.parsed
        skipped += acct.skipped
        broken += acct.broken
    accounting = ParseAccounting(
        lines_total=lines_total, parsed=parsed, skipped=skipped, broken=broken
    )

    if store is None:
        unique, duplicates = dedupe(observations)
        in_window, filtered_out = filter_window(unique, since=since, until=until)
        return Wh1ShadowHarvestReport(
            sources=[str(p) for p in paths],
            accounting=accounting,
            input_duplicates=duplicates,
            store_path=None,
            ledger_existing=0,
            ledger_broken=0,
            appended=0,
            filter_since=since.isoformat() if since is not None else None,
            filter_until=until.isoformat() if until is not None else None,
            filtered_out=filtered_out,
            summary=summarize(in_window),
        )

    ledger_obs, ledger_broken = load_ledger(store)
    seen: set[DedupKey] = set()
    # 원장 자체도 dedup해 로드한다(과거 도구 밖 수기 append 등 방어) — seen에 키 누적.
    ledger_unique, _ledger_dups = dedupe(ledger_obs, seen=seen)
    new_obs, duplicates = dedupe(observations, seen=seen)
    _append_ledger(store, new_obs)
    # 축적은 *무필터*(원장은 전부 보존) — 필터는 **집계 창**에만 적용한다(축적 ≠ 판정 분모).
    in_window, filtered_out = filter_window(ledger_unique + new_obs, since=since, until=until)
    return Wh1ShadowHarvestReport(
        sources=[str(p) for p in paths],
        accounting=accounting,
        input_duplicates=duplicates,
        store_path=str(store),
        ledger_existing=len(ledger_unique),
        ledger_broken=ledger_broken,
        appended=len(new_obs),
        filter_since=since.isoformat() if since is not None else None,
        filter_until=until.isoformat() if until is not None else None,
        filtered_out=filtered_out,
        summary=summarize(in_window),  # 구간 미지정이면 원장 전체 기준(기존 동작 불변)
    )


def _fmt_ratio(value: float) -> str:
    """비율 표기 — 소수 1자리 %."""
    return f"{value * 100:.1f}%"


def _fmt_duration(label: str, dur: DurationSummary | None) -> str:
    if dur is None:
        return f"  {label:<14}: (소요 기록 턴 없음)"
    return f"  {label:<14}: n={dur.n} · p50 {dur.p50}ms · p90 {dur.p90}ms · max {dur.max}ms" + (
        " ⚠ 표본이 작아 백분위가 거칠다" if dur.n < 20 else ""
    )


def _render_primary_section(s: Wh1ShadowDistributionSummary) -> list[str]:
    """primary 채택률 절 — **작동한 비율**을 리포트가 직접 말한다(OPS-134 ②·작동 비율 원칙).

    시도 0건이면 "0%"가 아니라 "분모 없음"을 쓴다. 구판 primary 레코드가 있으면 그 수와 함께
    "이 비율은 결말 계측 이후 구간만의 값"임을 밝힌다.
    """
    lines = ["[primary 채택률 — 학생이 LLM 발화를 받은 턴 비율(OPS-134)]"]
    if s.primary_attempts == 0:
        lines.append("  (결말 기록 primary 시도 0건 — 채택률 산출 불가·0%로 위장하지 않음)")
    else:
        rate = s.primary_adoption_rate
        lines.append(
            f"  시도 n={s.primary_attempts} · 채택 {s.primary_adopted}건"
            + (f" ({_fmt_ratio(rate)})" if rate is not None else "")
        )
        for label in PRIMARY_OUTCOME_LABELS:
            lines.append(f"  {label:<26}: {s.primary_outcome_counts.get(label, 0)}건")
        lines.append(_fmt_duration("소요(채택 턴)", s.elapsed_ms_adopted))
        lines.append(_fmt_duration("소요(폴백 턴)", s.elapsed_ms_fallback))
        share = s.fallback_llm_call_share
        lines.append(
            f"  LLM 호출: 채택 턴 {s.llm_calls_in_adopted}건 · 폴백 턴 {s.llm_calls_in_fallback}건"
            + (f" — 폴백 턴 비중 {_fmt_ratio(share)}" if share is not None else "")
            + f" (기록 시도 {s.llm_calls_accounted}/{s.primary_attempts})"
        )
        if s.llm_calls_in_fallback > 0:
            lines.append(
                "  ⚠ 폴백 턴의 LLM 호출은 출력이 학생에게 닿지 않았지만 Langfuse에는 serving"
                " 표지로 전송돼 있다 — 게이트② 학생 대면 표본에 포함된 호출이다(제외하지 않고"
                " 비중을 보고)."
            )
        if s.timeout_turns > 0:
            other_ms = s.timeout_elapsed_ms_total - s.timeout_llm_ms_total
            lines.append(
                f"  타임아웃 {s.timeout_turns}턴: 소요 합 {s.timeout_elapsed_ms_total}ms 중"
                f" 끝난 LLM 호출 {s.timeout_llm_ms_total}ms · 나머지 {other_ms}ms는 취소된 호출 "
                f"({s.timeout_inflight_calls}건 비행 중)+비LLM 단계(둘은 로그만으로 갈리지 않음)"
            )
    if s.primary_legacy_records > 0:
        lines.append(
            f"  ⚠ 결말 미기록 구판 primary 레코드 {s.primary_legacy_records}건은 분모에서 제외"
            " — 이 채택률은 결말 계측 이후 구간만의 값이다(구판은 폴백 기록이 0줄이었다)."
        )
    return lines


def render_report(report: Wh1ShadowHarvestReport) -> str:
    """사람용 리포트 — 회계·분포를 표기하되 **판정선을 내지 않는다**(분포 제시가 목적)."""
    s = report.summary
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("WH-1 shadow verify verdict 수확 — 분포 리포트(판정선 없음)")
    lines.append("=" * 64)
    lines.append(f"입력: {', '.join(report.sources)}")
    lines.append(
        f"[파싱 회계] 라인 {report.accounting.lines_total} · parsed {report.accounting.parsed} "
        f"· 비해당 skip {report.accounting.skipped} · 깨진 JSON {report.accounting.broken}"
    )
    if report.store_path is not None:
        lines.append(
            f"[원장 축적] {report.store_path} — 기존 {report.ledger_existing} · "
            f"신규 append {report.appended} · 중복 걸러냄 {report.input_duplicates} · "
            f"원장 깨진 라인 {report.ledger_broken}"
        )
    else:
        lines.append(f"[무축적] --store 미지정 — 이번 입력만 집계(중복 {report.input_duplicates})")
    if report.filter_since is not None or report.filter_until is not None:
        lines.append(
            f"[집계 구간] since={report.filter_since or '하한 없음'} · "
            f"until={report.filter_until or '상한 없음'} — 구간 밖 제외 {report.filtered_out}건"
            " (원장에는 남아 있음·이 분포는 *구간 표본*이다)"
        )
    else:
        lines.append("[집계 구간] 미지정 — 원장/입력 전체 기준 분포(회차 분리 없음)")
    lines.append(
        f"[관측 총 n] {s.total} · 고유 dialogue {s.distinct_dialogues}"
        f" · 하네스 중단 턴 {s.aborted_total}건(아래 분포에는 불포함 — primary 채택률 절에서 센다)"
    )
    if s.observed_at_min is not None and s.observed_at_max is not None:
        lines.append(
            f"[관측 시각] {s.observed_at_min.isoformat()} ~ {s.observed_at_max.isoformat()}"
        )
    lines.extend(_render_primary_section(s))
    lines.append("[verify verdict 분포 — none=verify 미호출]")
    for label in _VERDICT_LABELS:
        count = s.verdict_counts.get(label, 0)
        ratio = f" ({_fmt_ratio(s.verdict_ratios[label])})" if label in s.verdict_ratios else ""
        lines.append(f"  {label:<12}: {count}건{ratio}")
    # 판정 모집단(none 제외) — 사전등록 판정문의 분모. 위 4-라벨 비율과 분모가 다르다는 사실을
    # 같은 화면에 병기해 "화면 숫자를 그대로 읽는" 오독을 구조적으로 막는다(판정선은 없음).
    lines.append("[판정 모집단 — verify 호출 턴만(none 제외·사전등록 분모)]")
    lines.append(f"  모집단 n     : {s.verify_target_total}건 (위 총 n {s.total} 중)")
    if s.verify_target_ratios:
        for label in VERIFY_TARGET_LABELS:
            count = s.verdict_counts.get(label, 0)
            lines.append(f"  {label:<12}: {count}건 ({_fmt_ratio(s.verify_target_ratios[label])})")
    else:
        lines.append("  (모집단 0건 — 비율 산출 불가·0%로 위장하지 않음)")
    # 전이 형태 축(S3-51) — S3-02 해집합 경로가 실제로 작동한 횟수·혼합 형태 잔여.
    lines.append("[전이 형태 — 등호 방정식(해집합 경로·S3-02) / 혼합 형태]")
    lines.append(
        f"  형태 축 보유 {s.form_records}건 · 구판(축 미보유) {s.form_legacy_records}건 "
        "— 구판은 합산 제외(정직 회계)"
    )
    if s.form_records > 0:
        lines.append(
            f"  {'Σ등호 방정식 전이':<16}: {s.form_transition_counts.get('equation', 0)}건"
        )
        lines.append(f"  {'Σ혼합 형태 전이':<16}: {s.form_transition_counts.get('mixed', 0)}건")
        lines.append(f"  {'등호 전이 >=1 턴':<16}: {s.equation_turns}건")
    else:
        lines.append("  (합산 불가 — 형태 축 보유 레코드 0건)")
    lines.append("[status 분포]")
    if s.status_counts:
        for status, count in s.status_counts.items():
            lines.append(f"  {status:<16}: {count}건")
    else:
        lines.append("  (관측 없음)")
    lines.append("[turn_index별 verdict 분포]")
    if s.turn_verdicts:
        for turn_index, per_turn in s.turn_verdicts.items():
            detail = " ".join(f"{k}={v}" for k, v in sorted(per_turn.items()))
            lines.append(f"  turn {turn_index}: {detail}")
    else:
        lines.append("  (관측 없음)")
    # 전이별 집계(S3-07) — 턴당 verify_step *전* 판정 합산. 마지막 판정 축이 가리는 앞 전이
    # correct를 보이게 하는 추가 축이며, 구판(카운트 미보유)은 분리 표기한다(0으로 위장 금지).
    lines.append("[전이별 집계 — 턴당 verify_step 전 판정 합산(S3-07)]")
    lines.append(
        f"  카운트 보유(신판) {s.transition_records}건 · 구판(카운트 미보유) "
        f"{s.legacy_records}건 — 구판은 합산 제외(정직 회계)"
    )
    if s.transition_records > 0:
        for label in ("correct", "incorrect", "unverifiable"):
            lines.append(f"  {'Σn_' + label:<16}: {s.transition_counts.get(label, 0)}건")
    else:
        lines.append("  (합산 불가 — 전이 카운트 보유 레코드 0건)")
    lines.append("=" * 64)
    lines.append("판정선 없음 — 이 분포는 S1-11 flip 전제 ①의 *근거 자료*다. 승격 판정은")
    lines.append("사람/별도 게이트가 내린다(임의 cutoff 단정 금지 — CLAUDE.md '모르면 모른다').")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 로그 수확·(옵션) 원장 축적·분포 리포트. 성공 0·입력 오류 2."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.wh1_shadow_harvest",
        description=(
            "WH-1 하네스 shadow 관측(record 로거 JSON) 수확·축적기 — 서버 로그에서 record "
            "라인만 파싱해 verify verdict 분포를 낸다(S1-11 flip 전제 ①·판정선 없음)."
        ),
    )
    parser.add_argument(
        "log_paths",
        nargs="+",
        type=str,
        help="서버 로그 파일 경로(들) — record 라인/순수 JSONL 혼재 허용.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help="누적 원장 ndjson 경로 — 있으면 dedup 후 신규만 append·원장 전체 기준 집계.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help=(
            "집계 구간 시작(ISO 8601·포함) — 예 2026-09-22T09:00:00+09:00. 원장은 축적이라 "
            "이전 회차가 같은 분모에 남는다. 회차 하나를 판정하려면 이 구간을 준다."
        ),
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="집계 구간 끝(ISO 8601·포함). 미지정이면 상한 없음.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_out",
        help="리포트 JSON 출력 경로(선택).",
    )
    args = parser.parse_args(argv)
    log_paths: list[str] = args.log_paths
    store: Path | None = args.store
    json_out: Path | None = args.json_out

    # 구간 인자 파싱 — 형식 오류는 조용히 무시하지 않고 입력 오류(exit 2)로 거부한다.
    # 잘못 적힌 --since를 무시하면 "필터가 걸린 줄 알았는데 원장 전체를 판정"이 된다.
    bounds: dict[str, datetime | None] = {"since": None, "until": None}
    for name in ("since", "until"):
        raw: str | None = getattr(args, name)
        if raw is None:
            continue
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError as exc:
            print(
                f"--{name} 파싱 실패({type(exc).__name__}): {raw!r} — ISO 8601이어야 한다"
                " (예 2026-09-22T09:00:00+09:00)",
                file=sys.stderr,
            )
            return _EXIT_ERROR
        if moment.tzinfo is None:
            # 해석 규칙을 숨기지 않는다 — naive 입력은 UTC로 간주하고 그 사실을 알린다.
            print(
                f"⚠ --{name}에 시간대가 없어 UTC로 해석한다: {moment.isoformat()}Z"
                " (KST로 주려면 +09:00을 붙인다)",
                file=sys.stderr,
            )
            moment = moment.replace(tzinfo=timezone.utc)
        bounds[name] = moment

    since, until = bounds["since"], bounds["until"]
    if since is not None and until is not None and since > until:
        print(
            f"--since({since.isoformat()})가 --until({until.isoformat()})보다 늦다", file=sys.stderr
        )
        return _EXIT_ERROR

    try:
        report = harvest_files([Path(p) for p in log_paths], store=store, since=since, until=until)
    except OSError as exc:
        # 부분 수확을 리포트로 위장하지 않는다 — 어떤 파일이 왜 안 읽혔는지 타입명과 함께 보고.
        print(f"로그 파일 읽기 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_ERROR

    print(render_report(report))
    if json_out is not None:
        json_out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"JSON 리포트 저장: {json_out}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main/harvest_files가 테스트 대상
    sys.exit(main())
