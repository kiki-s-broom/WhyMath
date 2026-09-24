"""앵커 축적 **회차 대장** — '작동한 비율'(EOS-64 ②)과 연속 무진전 알람(④)의 단일 원천.

왜 이 모듈이 있는가
------------------
EOS-58이 앵커 A4 관통을 1회 실증했지만, 그 관통이 *상시로* 일하고 있는지는 아무도 재지
않았다. 라이브 회차가 exit 0을 내도 그것은 "이번에 1건 붙었다"일 뿐이고, exit 1을 내도 그것이
"이번 회차만 안 붙었다"인지 "구조적으로 3주째 안 붙는다"인지 구분되지 않는다 — CLAUDE.md
"작동 신호 없는 알고리즘 부착 금지"("정상 응답 200은 알고리즘이 일했다는 증거가 아니다")가
정확히 이 공백을 가리킨다. 이 모듈이 그 두 공백을 메운다:

  ② **작동한 비율**(`operating_rates`) — 회차 리포트에 outcome 6종의 *분포*를 싣는다. 수용
     1건이라는 사실보다 "5시도 중 수용1·검수필요1·게이트거부1·중복1·생성실패1"이라는 분포가
     파이프라인의 각 단계가 실제로 일했다는 증거다(전건 generation_failed면 게이트·dedup은
     한 번도 안 돌았다는 뜻이고, 그건 exit 1 하나로는 안 보인다).
  ④ **연속 무진전 알람**(`judge_stagnation`) — 회차 1건씩을 append-only 대장에 남기고, 최신
     회차부터 연속으로 코퍼스가 자라지 않은 횟수를 센다. fail-open 상시 실패(같은 경고가
     매번 나는데 아무도 안 보는 상태)를 막으려면 *반복*이 판정으로 승격돼야 한다.

판정 방향 — 점추정 금지(CLAUDE.md 검증 권위)
--------------------------------------------
비율은 점추정으로 말하지 않는다. `harness/wilson`의 단측 경계를 **지표 성격에 맞는 방향**으로
쓴다(재구현 0 — 그 모듈이 단일 원천):

  - `accepted_stored`·`accepted` = "높을수록 좋은" 수용률 → **하한**(`wilson_lower_bound`).
    5/5=1.0 같은 작은 표본의 과신을 막는다(정직 — 실제보다 낮게 본다).
  - `needs_review`·`rejected_gate`·`rejected_duplicate`·`generation_failed` = "낮을수록 좋은"
    비용·결함 축 → **상한**(`wilson_upper_bound`). 0/3 관측을 "확정 0%"로 읽지 않는다.
    `needs_review`를 결함이 아니라 *사람 검수 비용*으로 보더라도 방향은 같다(적을수록 좋다).

분모 0은 "0%"가 아니라 **측정 불가**다(CLAUDE.md 미측정≠0). `attempted <= 0`이면 전 비율이
`None`이고 `measured=False`·`unmeasured_reason`이 사유를 말한다 — 0.0으로 채우면 "시도한 적
없음"이 "전건 실패"와 같은 색이 된다.

무진전의 축 — `appended`(코퍼스 성장)를 본다
-------------------------------------------
acceptance 문구는 "수용 0"이지만 이 모듈이 세는 축은 `appended`(실제로 코퍼스 JSONL에 붙은
신규 행)다. 근거: ⑴ `problem_corpus_accumulate.main`의 기존 exit 판정이 이미 `appended > 0`
이라 같은 축을 써야 신호가 갈리지 않고 ⑵ `appended > 0`이면 정의상 `accepted > 0`이지만
역은 아니다(수용됐는데 slug 충돌로 전건 스킵되면 코퍼스는 그대로다) — 즉 `appended`가 더
엄격하고, "코퍼스가 자랐는가"라는 무진전의 본래 의미에 정확히 대응한다. 대장 행에는 두 값을
모두 남겨 나중에 다른 축으로 재판정할 수 있게 한다.

매체 계약(EOS-55 genlog·EOS-58 검수 큐와 동형)
---------------------------------------------
회차 1건 = JSONL 1행, **발생 즉시 append+flush**(마지막 일괄 저장 금지 — 2026-08-22 규칙 ①).
로드 실패 줄은 삼키지 않고 **예외 타입명 + 줄 번호**만 수집한다(필드 *값*·원문 줄은 넣지
않는다 — 침묵 실패 금지). 행은 관측이므로 수정·삭제하지 않는다(append-only).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.equivalent.orchestrator import (
    DuplicateDetector,
    DuplicateOrigin,
    GenerationOutcome,
)

__all__ = [
    "ACCEPTED_STATUSES",
    "DUPLICATE_DETECTORS",
    "DUPLICATE_ORIGINS",
    "OUTCOME_STATUSES",
    "PROMPT_CACHE_STATES",
    "SEAT_STATES",
    "PromptCacheTally",
    "SeatTally",
    "RoundRecord",
    "StagnationVerdict",
    "append_round_ledger",
    "default_round_ledger_path",
    "duplicate_source_rates",
    "judge_stagnation",
    "load_round_ledger",
    "operating_rates",
    "prompt_cache_rates",
    "seat_operating_rates",
]

# outcome 어휘는 **오케스트레이터의 Literal에서 파생**한다(재선언 금지) — 여기 손으로 6종을
# 베껴 두면 orchestrator가 상태를 추가·개명할 때 리포트가 조용히 그 상태를 빠뜨린다(분포가
# 100%가 안 되는데 아무도 모르는 상태). EOS-58 테스트 docstring의 어휘 나열도 정본이 아니다.
OUTCOME_STATUSES: tuple[str, ...] = tuple(
    get_args(GenerationOutcome.model_fields["status"].annotation)
)
if "accepted_stored" not in OUTCOME_STATUSES or len(OUTCOME_STATUSES) < 2:
    # 도입부 파생이 깨지면 "분포가 빈 dict"로 조용히 통과할 수 있다 — 그건 측정 실패이므로
    # import 시점에 정직하게 터진다(2026-08-22 "정지 장치도 변별력이 필요하다"의 반대 축:
    # 여기서는 *위장 통과*를 막는 것이 목적이라 fail-fast가 옳다).
    raise RuntimeError(
        "GenerationOutcome.status Literal에서 outcome 어휘를 파생하지 못했다 — "
        f"파생 결과={OUTCOME_STATUSES!r}. 회차 분포가 위장 통과할 수 있어 import를 중단한다."
    )

# 중복 출처 어휘(EOS-121 B)도 **오케스트레이터의 Literal에서 파생**한다 — outcome 어휘와 같은
# 이유다(손으로 베끼면 축이 늘 때 리포트가 조용히 그 값을 빠뜨린다).
DUPLICATE_DETECTORS: tuple[str, ...] = tuple(get_args(DuplicateDetector))
DUPLICATE_ORIGINS: tuple[str, ...] = tuple(get_args(DuplicateOrigin))
if len(DUPLICATE_DETECTORS) < 2 or len(DUPLICATE_ORIGINS) < 2:
    raise RuntimeError(
        "중복 출처 어휘를 Literal에서 파생하지 못했다 — "
        f"detectors={DUPLICATE_DETECTORS!r} origins={DUPLICATE_ORIGINS!r}. "
        "출처 교차표가 위장 통과할 수 있어 import를 중단한다."
    )

#: 검출기/출처가 **없을 때** 쓰는 명시 키. None을 키에서 빼면 "구분이 안 된 건"이 교차표에서
#: 사라져 합계가 안 맞는데도 아무도 모른다 — 미판정은 값이지 부재가 아니다(미측정 ≠ 0).
_UNCLASSIFIED_DETECTOR = "unclassified"
_UNKNOWN_ORIGIN = "unknown"

# 수용 축 — `needs_review_worklist._STORED_STATUSES`·`run_corpus_accumulate`의 비수용 판정과
# 같은 집합(두 곳이 이미 이 두 값을 쓴다). 여기서는 *비율 방향*을 가르는 데 쓴다.
ACCEPTED_STATUSES: frozenset[str] = frozenset({"accepted_stored", "accepted"})

# 기본 신뢰수준 — 저장소 전 게이트 관례(`ops/qa_confusion_matrix._CONFIDENCE` 동일).
_CONFIDENCE = 0.95

# 연속 무진전 기본 창(회차) — 2회는 소량 n 회차에서 흔한 잡음이고(대본 1건짜리 회차도 있다),
# 3회 연속이면 "이번엔 운이 없었다"로 설명되지 않는 구조 신호다. `--stagnation-window`로 조정.
DEFAULT_STAGNATION_WINDOW = 3


def _bound_direction(status: str) -> str:
    """이 outcome이 '높을수록 좋은' 축인지 — 수용은 하한, 나머지(비용·결함)는 상한."""
    return "lower" if status in ACCEPTED_STATUSES else "upper"


def operating_rates(
    outcome_counts: dict[str, int],
    *,
    attempted: int,
    confidence: float = _CONFIDENCE,
) -> dict[str, Any]:
    """회차 '작동한 비율' — outcome 6종 분포 + 방향별 Wilson 단측 경계(순수·파일 I/O 0).

    반환 dict는 회차 리포트에 그대로 실린다(`AccumulateReport.to_json`). 구조:

        {"attempted": 5, "measured": true, "confidence": 0.95,
         "unmeasured_reason": null,
         "statuses": {"accepted_stored": {"count":1, "rate":0.2,
                                          "bound":0.036, "bound_direction":"lower"}, ...},
         "unknown_statuses": {}}

    - `statuses`는 **어휘 전건**을 싣는다(관측 0인 상태도 count 0으로 명시) — 키가 없는 것과
      0건인 것은 다르다. 어휘 밖 상태가 들어오면 버리지 않고 `unknown_statuses`에 카운트만
      남긴다(조용한 누락 금지 — 어휘 드리프트를 리포트가 자백한다).
    - `attempted <= 0`이면 `measured=false`이고 전 `rate`·`bound`가 `None`이다(미측정≠0).
    - `rate`는 점추정이라 **판정 근거가 아니다**(참고용 표시). 판정은 `bound`로 한다.
    """
    measured = attempted > 0
    reason: str | None = (
        None if measured else f"시도 {attempted}회 — 분모가 없어 비율을 계산할 수 없다(0%가 아니다)"
    )

    statuses: dict[str, Any] = {}
    for status in OUTCOME_STATUSES:
        count = int(outcome_counts.get(status, 0))
        direction = _bound_direction(status)
        rate: float | None = None
        bound: float | None = None
        if measured:
            rate = count / attempted
            bound = (
                wilson_lower_bound(count, attempted, confidence)
                if direction == "lower"
                else wilson_upper_bound(count, attempted, confidence)
            )
        statuses[status] = {
            "count": count,
            "rate": rate,
            "bound": bound,
            "bound_direction": direction,
        }

    unknown = {
        status: int(count)
        for status, count in outcome_counts.items()
        if status not in OUTCOME_STATUSES
    }
    return {
        "attempted": attempted,
        "measured": measured,
        "confidence": confidence,
        "unmeasured_reason": reason,
        "statuses": statuses,
        "unknown_statuses": unknown,
    }


# ──────────────────────────────────────────────────────────────────────────
# 중복 출처 '작동한 비율' (EOS-121 선결조건 B) — 구분 장치가 실제로 구분했는가
#
# 「작동한 비율」 원칙(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지"): 출처 구분 장치를 붙였으면
# **그것이 실제로 작동한 비율**을 회차 요약이 말해야 한다. `rejected_duplicate` 4건이 나왔는데
# 4건 모두 출처 `unknown`이면, 장치는 붙어 있으나 이 회차에서는 **한 번도 일하지 않은 것**이다
# (좌석 미주입·구판 경로). 그 상태와 "4건 전부 코퍼스 중복"은 조치가 정반대인데 종전에는 둘 다
# 그냥 `rejected_duplicate: 4`로 보였다.
# ──────────────────────────────────────────────────────────────────────────


def duplicate_source_rates(
    pairs: Sequence[tuple[str | None, str | None]],
) -> dict[str, Any]:
    """중복 출처 교차표 + 구분 장치의 작동 비율(순수·파일 I/O 0).

    `pairs`는 이 회차의 **`rejected_duplicate` outcome 전건**의
    `(duplicate_detector, duplicate_origin)`이다 — 중복이 아닌 outcome은 넣지 않는다(분모가
    부풀어 "구분 못 한 비율"이 희석된다).

    반환 구조:

        {"duplicates_total": 4, "measured": true, "unmeasured_reason": null,
         "classified": 4, "classified_rate": 1.0,
         "origin_resolved": 3, "origin_resolved_rate": 0.75,
         "counts": {"structural_signature/round": 2, ...},   # 어휘 전건(미판정 키 포함)
         "by_detector": {...}, "by_origin": {...},
         "unknown_detectors": {}, "unknown_origins": {}}

    - `counts`는 **어휘 전건**을 싣는다(관측 0인 조합도 0으로 명시) — 키 부재와 0건은 다르다.
      어휘 밖 값은 버리지 않고 `unknown_detectors`/`unknown_origins`에 남긴다(어휘 드리프트 자백).
    - `duplicates_total == 0`이면 `measured=false`이고 두 비율이 `None`이다. 중복이 0건인 회차는
      구분 장치가 **일할 일이 없었던** 것이지 실패한 것이 아니다(미측정 ≠ 0 — 0.0으로 채우면
      "구분 0% 달성"이라는 거짓 경보가 된다).
    - `classified_rate`는 "중복 중 **검출기**를 아는 비율", `origin_resolved_rate`는 "중복 중
      **출처**까지 아는 비율"이다. 둘을 나누는 이유: 검출기는 orchestrator가 항상 채우고 출처만
      좌석 주입에 달려 있어, 한 숫자로 접으면 *어느 쪽이 빠졌는지* 알 수 없다.
    """
    total = len(pairs)
    measured = total > 0
    reason: str | None = (
        None
        if measured
        else (
            "이 회차 rejected_duplicate 0건 — 구분할 대상이 없어 비율을 계산할 수 "
            "없다(0%가 아니다)"
        )
    )

    detector_keys = (*DUPLICATE_DETECTORS, _UNCLASSIFIED_DETECTOR)
    origin_keys = (*DUPLICATE_ORIGINS, _UNKNOWN_ORIGIN)
    counts: dict[str, int] = {f"{d}/{o}": 0 for d in detector_keys for o in origin_keys}
    by_detector: dict[str, int] = {key: 0 for key in detector_keys}
    by_origin: dict[str, int] = {key: 0 for key in origin_keys}
    unknown_detectors: dict[str, int] = {}
    unknown_origins: dict[str, int] = {}

    classified = 0
    origin_resolved = 0
    for detector, origin in pairs:
        if detector is None:
            detector_key = _UNCLASSIFIED_DETECTOR
        elif detector in DUPLICATE_DETECTORS:
            detector_key = detector
            classified += 1
        else:
            # 어휘 밖 — 교차표에는 미분류로 계상하되 원값을 따로 남긴다(조용한 누락 금지).
            detector_key = _UNCLASSIFIED_DETECTOR
            unknown_detectors[detector] = unknown_detectors.get(detector, 0) + 1

        if origin is None:
            origin_key = _UNKNOWN_ORIGIN
        elif origin in DUPLICATE_ORIGINS:
            origin_key = origin
            origin_resolved += 1
        else:
            origin_key = _UNKNOWN_ORIGIN
            unknown_origins[origin] = unknown_origins.get(origin, 0) + 1

        counts[f"{detector_key}/{origin_key}"] += 1
        by_detector[detector_key] += 1
        by_origin[origin_key] += 1

    return {
        "duplicates_total": total,
        "measured": measured,
        "unmeasured_reason": reason,
        "classified": classified,
        "classified_rate": (classified / total) if measured else None,
        "origin_resolved": origin_resolved,
        "origin_resolved_rate": (origin_resolved / total) if measured else None,
        "counts": counts,
        "by_detector": by_detector,
        "by_origin": by_origin,
        "unknown_detectors": unknown_detectors,
        "unknown_origins": unknown_origins,
    }


# ──────────────────────────────────────────────────────────────────────────
# 프롬프트 캐시 '작동한 비율' (EOS-99) — 켰다는 사실과 작동했다는 사실을 가른다
#
# `settings.anthropic_prompt_caching`을 켜면 요청에 `cache_control`이 실린다. 그러나 그것은
# **켰다는 사실**일 뿐이다 — 프리픽스가 최소 토큰 미만이면 API는 조용히 캐시하지 않고
# (silent no-op), 프리픽스가 회차마다 달라지면 매번 새로 쓰기만 한다. 두 경우 모두 응답은
# 200이고 회차는 exit 0이다. 그래서 적중은 **응답 usage로만** 판정된다(CLAUDE.md
# "작동 신호 없는 알고리즘 부착 금지").
#
# 분모 주의 — `input_tokens`는 캐시 적중분을 **뺀** 값이다(배타 관계). 그래서 적중률의
# 분모는 `input + cache_read + cache_creation`(= 프롬프트 총 토큰)이다. acceptance ②의
# 표기 "cache_read/input"을 글자대로 읽으면 분모가 캐시 적중분을 제외한 잔여만 남아 비율이
# 1을 훌쩍 넘고, 같은 acceptance ③이 정상값으로 지정한 "(n-1)/n에 근접"과 모순된다 —
# 행동 기준(③)이 계약이므로 분모를 총 프롬프트 토큰으로 잡는다. n회 동일 프리픽스 회차에서
# 1회차가 쓰고(P) 2~n회차가 읽으면((n-1)P) 비율은 (n-1)P/(nP) = (n-1)/n으로 수렴한다.
# ──────────────────────────────────────────────────────────────────────────

#: 상태 어휘 전건 — 리포트·대장을 읽는 쪽이 문자열을 상수로 대조할 수 있게 공개한다.
#
# 키 이름이 `verdict`가 **아닌** 이유: 회차 대장은 "검수자 착석 필드(reviewer_id·verdict)를
# 담지 않는다"를 문자열 부재로 동결한 가드가 있다(`test_eos_anchor_e2e_a4.py::
# TestGenerationLogAnchorHonesty`). 이 상태는 기계 산출이라 그 가드의 *의도*에는 걸리지
# 않지만, 가드를 느슨하게 고쳐 통과시키는 것보다 이름을 비켜 주는 편이 옳다 — 그 가드의
# 힘은 **중첩된 어디에 있든 잡는 무딤**에서 나오고, 예외를 파는 순간 그 힘이 사라진다.
PROMPT_CACHE_STATES: tuple[str, ...] = (
    "not_applicable",
    "unmeasured",
    "disabled",
    "disabled_but_hit",
    "enabled_not_working",
    "enabled_working",
    "unknown_flag",
)


@dataclass(frozen=True, slots=True)
class PromptCacheTally:
    """회차 안 genlog 행에서 모은 프롬프트 캐시 원장(불변·순수·파일 I/O 0).

    `observe`는 **새 인스턴스를 돌려준다** — 싱크가 회차 도중 값을 누적하되, 중간 상태가
    다른 곳에서 조용히 바뀌지 않게 한다(대장 행은 회차 끝의 스냅샷 하나만 본다).

    **캐시 텔레메트리가 없는 행의 `input_tokens`는 분모에 넣지 않는다.** 이것이 이 집계의
    급소다: 로컬 Ollama 경로는 캐시 개념 자체가 없어 두 캐시 필드가 None인데, 그 행의 입력
    토큰을 분모에 실으면 **로컬만 돌린 회차가 '적중 0%'로 보인다** — 즉 "해당 없음"이
    "켰지만 작동 안 함"으로 위장된다(미측정 ≠ 0). 그래서 분모는 캐시 필드를 하나라도 실은
    행(= 클라우드 응답)에서만 모은다.
    """

    calls_total: int = 0
    """관측한 genlog 행 수(전체) — 분모가 아니라 *관측 규모*다."""

    calls_with_cache_telemetry: int = 0
    """캐시 필드를 하나라도 실은 행 수 — 이 값이 0이면 적중률은 정의되지 않는다."""

    cache_read_tokens: int = 0
    """캐시에서 읽힌 프리픽스 토큰 합(적중분)."""

    cache_creation_tokens: int = 0
    """캐시에 쓰인 프리픽스 토큰 합(첫 회차분)."""

    uncached_input_tokens: int = 0
    """캐시 텔레메트리를 실은 행의 `input_tokens` 합(= 캐시를 타지 않은 잔여 입력)."""

    def observe(
        self,
        *,
        input_tokens: int | None,
        cache_read_input_tokens: int | None,
        cache_creation_input_tokens: int | None,
    ) -> PromptCacheTally:
        """genlog 행 1건을 반영한 새 원장을 돌려준다(원본 불변).

        None은 **더하지 않는다**(0으로 접지 않는다) — 미기록과 실측 0의 구분이 이 집계의
        전부이기 때문이다. 캐시 두 필드가 모두 None인 행은 `calls_total`만 늘린다.
        """
        has_cache = cache_read_input_tokens is not None or cache_creation_input_tokens is not None
        if not has_cache:
            return replace(self, calls_total=self.calls_total + 1)
        return replace(
            self,
            calls_total=self.calls_total + 1,
            calls_with_cache_telemetry=self.calls_with_cache_telemetry + 1,
            cache_read_tokens=self.cache_read_tokens + (cache_read_input_tokens or 0),
            cache_creation_tokens=self.cache_creation_tokens + (cache_creation_input_tokens or 0),
            uncached_input_tokens=self.uncached_input_tokens + (input_tokens or 0),
        )

    @property
    def prompt_tokens_total(self) -> int:
        """적중률의 분모 — 프롬프트 총 토큰(잔여 입력 + 읽기 + 쓰기·배타 관계 합산)."""
        return self.uncached_input_tokens + self.cache_read_tokens + self.cache_creation_tokens


def prompt_cache_rates(tally: PromptCacheTally, *, caching_enabled: bool | None) -> dict[str, Any]:
    """회차의 프롬프트 캐시 '작동한 비율' + 판정(순수·파일 I/O 0).

    `caching_enabled`는 이 회차가 돌 때의 `settings.anthropic_prompt_caching`이다. **None은
    "플래그 상태를 모른다"**이며 False(꺼짐)와 구분한다 — 모르는 것을 꺼짐으로 접으면
    적중 0%가 "당연한 결과"로 읽혀 '켰지만 작동 안 함'이 영영 안 보인다(모른다 ≠ 아니다).

    상태 어휘(`PROMPT_CACHE_STATES`) — 측정 가능성을 먼저 보고, 그다음에 플래그를 본다:

      - `not_applicable` — 캐시 텔레메트리를 실은 행이 0건. 로컬 경로만 돈 회차이거나
        provider가 필드를 노출하지 않은 경우다. **적중 0%가 아니다.**
      - `unmeasured` — 텔레메트리 행은 있는데 토큰 합이 0(분모 없음). 비율은 None.
      - `disabled` / `disabled_but_hit` — 플래그가 꺼져 있었다. 후자는 그런데도 적중이
        잡힌 경우로, 리포트가 읽은 플래그와 실제로 돈 설정이 다르다는 신호다(조용히 넘기지
        않는다).
      - `enabled_not_working` — **켰는데 적중 0%.** 이 태스크가 존재하는 이유다.
      - `enabled_working` — 켰고 적중이 있다.
      - `unknown_flag` — 측정은 됐으나 플래그 상태 미상.
    """
    measured = tally.calls_with_cache_telemetry > 0 and tally.prompt_tokens_total > 0
    hit_rate: float | None = None
    unmeasured_reason: str | None = None
    if tally.calls_with_cache_telemetry <= 0:
        state = "not_applicable"
        unmeasured_reason = (
            f"캐시 토큰을 실은 호출 0건(관측 {tally.calls_total}건) — 캐시 개념이 없는 로컬 "
            "경로만 돌았거나 provider가 필드를 노출하지 않았다. 적중 0%가 아니다(미측정)."
        )
    elif tally.prompt_tokens_total <= 0:
        state = "unmeasured"
        unmeasured_reason = (
            f"캐시 텔레메트리 {tally.calls_with_cache_telemetry}건이 있으나 프롬프트 토큰 합이 "
            "0 — 분모가 없어 비율을 계산할 수 없다(0%가 아니다)."
        )
    else:
        hit_rate = tally.cache_read_tokens / tally.prompt_tokens_total
        if caching_enabled is None:
            state = "unknown_flag"
        elif caching_enabled:
            state = "enabled_working" if hit_rate > 0 else "enabled_not_working"
        else:
            state = "disabled_but_hit" if hit_rate > 0 else "disabled"

    return {
        "caching_enabled": caching_enabled,
        "calls_total": tally.calls_total,
        "calls_with_cache_telemetry": tally.calls_with_cache_telemetry,
        "cache_read_tokens": tally.cache_read_tokens,
        "cache_creation_tokens": tally.cache_creation_tokens,
        "uncached_input_tokens": tally.uncached_input_tokens,
        "prompt_tokens_total": tally.prompt_tokens_total,
        "measured": measured,
        "unmeasured_reason": unmeasured_reason,
        "hit_rate": hit_rate,
        "state": state,
    }


class RoundRecord(BaseModel):
    """회차 대장 1행 — 축적 배치 1회의 결과 요약(append-only·관측).

    `appended`가 무진전 판정 축이고 `accepted`는 참조 축이다(모듈 docstring "무진전의 축").
    `outcome_counts`를 함께 남겨 나중에 대장만으로 분포를 재계산할 수 있게 한다 — 리포트
    JSON을 따로 보관하지 않아도 회차 이력이 자족한다.

    회차 매니페스트(MP-04 — 아래 두 묶음)
    -------------------------------------
    종전 8필드는 "몇 건 시도해 몇 건 붙었나"만 말했다. 그래서 대장만 보고는 **이 회차가 어떤
    임계·어떤 모델·어떤 프롬프트로 돌았는가**를 알 수 없었고(genlog 조인이 있어야 겨우 모델을
    안다), 배치 안전장치가 실제로 무슨 판정을 냈는지도 대장에는 0건이었다. 회차 간 비교
    (지난주 대비 수용률 하락이 모델 교체 때문인지 임계 변경 때문인지)가 원리적으로 불가능한
    상태였다. 두 묶음을 분리해 싣는다 — **구성(무엇으로 돌렸나)**과 **관측(그래서 뭐가 나왔나)**
    은 성질이 다르고, 섞으면 "임계 0.9"와 "하한 0.34"가 같은 칸에서 읽힌다.

      ① 구성 스냅샷 — `prompt_version`·`model_name`·카나리 3종·중단 감시 2종·`dedup_input_digests`·
         `cli_argv`. 이 회차를 **재현**하는 데 필요한 입력 전부다(같은 명령·같은 시드 파일·같은
         임계로 다시 돌릴 수 있는가).
      ② 관측 판정 — `canary_passed`·`canary_rate`·`canary_lower_bound`·`canary_blocked`·
         `canary_advisory`·`aborted`·`abort_reason`. 게이트가 **작동했다는 신호**다(CLAUDE.md
         "작동 신호 없는 알고리즘 부착 금지" — 회차가 exit 0을 냈다는 사실은 카나리가 판정을
         냈다는 증거가 아니다).

    신설 필드는 **전부 Optional·기본 None**이다. 신설 이전에 기록된 구행은 이 필드가 없으므로
    `None`=**미기록**으로 읽히고, 로더가 소급해 값을 채우지 않는다(날조 금지 — 그 회차가 어떤
    임계로 돌았는지는 아무도 모른다는 것이 사실이다). 0·빈 문자열로 채우면 "끔"·"측정됨 0"과
    구분되지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(description="축적 회차 식별자(`AccumulateReport.run_id`와 조인).")
    out_path: str = Field(description="이 회차가 append한 코퍼스 JSONL 경로(대장의 소속 축).")
    attempted: int = Field(ge=0, description="생성 시도 횟수(분모 — 0이면 측정 불가).")
    accepted: int = Field(ge=0, description="게이트·dedup 통과 후 저장된 수용 건수.")
    appended: int = Field(ge=0, description="코퍼스에 실제로 붙은 신규 행 수(무진전 판정 축).")
    outcome_counts: dict[str, int] = Field(
        default_factory=dict, description="outcome 상태별 건수(분포 재계산 재료)."
    )
    recorded_at: datetime | None = Field(
        default=None, description="기록 시각(UTC) — append가 스탬프(매체가 찍는다)."
    )
    source_line: int | None = Field(
        default=None,
        description=(
            "매체 파생 필드 — 대장 JSONL에서의 1-기반 줄 번호. append는 기록하지 않고"
            "(파일이 줄 번호를 자칭하지 않음) 로더가 실제 위치를 주입한다."
        ),
    )

    # ── ① 구성 스냅샷(MP-04) — "이 회차를 무엇으로 돌렸는가"(재현 재료) ──────────────
    prompt_version: str | None = Field(
        default=None,
        description=(
            "이 회차가 실제로 쓴 프롬프트 정본 식별자(genlog 행의 `prompt_version` 동일 값 — "
            "정본 자산 내용 해시). 프롬프트가 바뀌면 수용률이 바뀌므로, 이 값이 없으면 회차 "
            "간 수용률 비교가 '모델이 나빠졌나 프롬프트가 바뀌었나'를 구분하지 못한다. "
            "회차에 genlog 행이 0건이면(생성 호출 자체가 없었던 회차) None=미기록. 한 회차에서 "
            "서로 다른 값이 관측되면 정렬 후 ','로 합쳐 싣는다 — 하나만 골라 적으면 그 행은 "
            "회차가 단일 프롬프트로 돌았다고 거짓말하게 된다."
        ),
    )
    model_name: str | None = Field(
        default=None,
        description=(
            "이 회차가 실제로 호출한 모델의 **핀 ID**(예 'qwen2.5:7b'·'claude-sonnet-4-6') — "
            "genlog 행의 `model_name`과 같은 값이다. 패밀리명이 아니라 핀 ID여야 '지난 회차와 "
            "같은 모델인가'가 기계 판정된다. genlog 0건이면 None=미기록, 복수 관측 시 "
            "`prompt_version`과 같은 규칙(정렬 후 ',' 결합)."
        ),
    )
    canary_size: int | None = Field(
        default=None,
        description=(
            "이 회차에 적용된 카나리 표본 수(`--canary`). **0은 '관문 끔'을 명시**하는 값이고 "
            "None은 미기록이다 — 둘을 같은 칸으로 접으면 '보호가 꺼져 있었다'가 '기록이 없다'와 "
            "구분되지 않는다."
        ),
    )
    canary_threshold: float | None = Field(
        default=None,
        description=(
            "카나리 통과에 요구한 Wilson 단측 하한 임계(`--canary-threshold`). 관측된 하한"
            "(`canary_lower_bound`)과 **짝으로** 있어야 '왜 막혔나/왜 통과했나'가 대장만으로 "
            "재구성된다(임계가 바뀐 회차와 품질이 바뀐 회차는 조치가 정반대다)."
        ),
    )
    canary_confidence: float | None = Field(
        default=None,
        description=(
            "카나리 Wilson 단측 신뢰수준(`--canary-confidence`). 같은 관측이라도 신뢰수준이 "
            "다르면 하한이 달라지므로, 이 값 없이는 회차 간 하한을 비교할 수 없다."
        ),
    )
    abort_window: int | None = Field(
        default=None,
        description=(
            "롤링 불량률 감시 창 크기(`--abort-window`). 0은 '감시 끔'을 명시한다(None=미기록). "
            "회차 길이가 이 값보다 짧으면 롤링 감시는 한 번도 판정하지 않는다 — 그 사실을 "
            "나중에 판정하려면 창 크기가 대장에 남아 있어야 한다."
        ),
    )
    abort_threshold: float | None = Field(
        default=None,
        description="롤링 창 불량률 중단 임계(`--abort-threshold`) — 초과 시 회차 즉시 중단.",
    )
    dedup_input_digests: dict[str, str | None] | None = Field(
        default=None,
        description=(
            "이 회차가 dedup 인덱스로 읽은 **입력 전부**의 경로→sha256(hex) 매핑 — `--seeds`와 "
            "**기존 `--out` 코퍼스**를 모두 포함한다(누적 축적은 2회차부터 이전 산출물을 "
            "signature 인덱스에 합치므로, out을 빼면 수용 판정에 실제로 쓰인 입력 하나가 "
            "대장에서 통째로 빠진다 — PR #1013 Codex P1). 지문은 배치 **시작 전** 상태에서 "
            "뜬다: 배치 뒤에 뜨면 이 회차가 out에 append한 바이트가 섞여 '소비한 입력'이 아니라 "
            "'산출 후 상태'가 되고, 재현하려는 사람이 그 해시를 맞출 방법이 없다. "
            "같은 명령을 다시 돌려도 입력이 그 사이 자랐으면 결과가 달라지므로 재현 계약에는 "
            "**입력 내용의 지문**이 필요하다. 해시를 계산하지 못한 경로(부재·읽기 실패)는 값이 "
            "None이다(키는 남긴다 — '그 경로를 dedup 입력으로 주었으나 읽지 못했다'는 사실 "
            "자체가 관측이며, 첫 회차의 아직 없는 out이 이 경우다). 빈 dict는 '입력 0건으로 "
            "돌았다'는 관측이고, 필드 자체가 None이면 미기록이다."
        ),
    )
    spec_plan: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "이 회차가 **순환시킨 spec 목록**(EOS-121 선결조건 C). 항목 1건 = "
            "`{spec_id, topic_hint, spec}`이며 `spec`은 `EquivalenceSpec` 직렬화 전문이다 — "
            "경로·해시가 아니라 *해석된 값*을 싣는 이유는 spec 파일이 나중에 바뀌어도 대장 행이 "
            "자족하게 하기 위해서다(`dedup_input_digests`가 지문을 쓰는 것과 다른 선택 — 그쪽은 "
            "파일이 크고 이쪽은 작다). 단일 spec 회차는 항목 1건이고, 필드 자체가 None이면 "
            "미기록(이 필드 신설 이전 구행)이다."
        ),
    )
    spec_outcome_counts: dict[str, dict[str, int]] | None = Field(
        default=None,
        description=(
            "spec_id → outcome 상태별 건수(EOS-121 C). **좌석 × spec 교차 집계의 절반**이다 — "
            "나머지 절반(좌석)은 같은 행의 `cloud_seat` 필드가 싣는다. "
            "**2026-09-19 정정**: 종전 문면은 '좌석은 회차 단위라 회차 안에서 spec만 갈라 두면 "
            "두 축이 완성된다'고 적었는데 **그 전제가 틀렸다** — 좌석이 회차 단위인 것은 맞지만 "
            "그 회차 단위 값이 대장에 *실리지 않아* 대장만으로는 어느 좌석의 회차인지 알 수 "
            "없었다(EOS-121 파일럿 실측: `cloud_seat`가 stdout 요약에만 있었고 대장 행에는 "
            "필드 자체가 없었다). 교차 집계는 두 필드가 **함께** 있어야 성립한다. "
            "이것이 없으면 spec을 3종 돌려도 '어느 spec이 무엇을 냈는지'가 합산으로 뭉개져 "
            "acceptance ②가 형식만 충족된다. 빈 dict는 '시도 0건', None은 미기록."
        ),
    )
    duplicate_sources: dict[str, Any] | None = Field(
        default=None,
        description=(
            "이 회차 중복의 **출처 교차표 + 구분 장치 작동 비율**(EOS-121 선결조건 B · "
            "`duplicate_source_rates` 산출물 그대로). 회차 대장에 싣는 이유는 이 구분이 "
            "**사후 복원 불가**이기 때문이다 — `signature_index`는 회차가 끝나면 기존분과 "
            "회차분이 섞인 한 덩어리라 나중에 어느 것이 어느 쪽이었는지 되살릴 수 없다. "
            "회차 중 기록하지 않으면 그 회차가 ③에 대해 아무것도 남기지 않는다. "
            "None=미기록(이 필드 신설 이전 구행), `measured=false`는 '중복 0건이라 잴 것이 "
            "없었다'로 0%와 구분된다."
        ),
    )
    cli_argv: list[str] | None = Field(
        default=None,
        description=(
            "이 회차를 띄운 CLI 인자 그대로(프로그램명 제외). 개별 파라미터 필드가 놓친 인자"
            "(`--topic-hint`·`--standard-code`·`--n` 등)까지 포함한 **재실행 가능한 원문**이다 "
            "— 스키마가 필드를 추가할 때마다 과거 회차를 소급 해석할 필요가 없어진다. "
            "빈 리스트는 '인자 없이 실행'이고 None은 미기록."
        ),
    )

    # ── ② 관측 판정(MP-04) — "그래서 게이트가 무슨 판정을 냈는가"(작동 신호) ─────────
    canary_passed: bool | None = Field(
        default=None,
        description=(
            "카나리 판정 결과. None은 **판정이 없었다**는 뜻이다(관문 꺼짐·시도 0건) — "
            "False(미달)와 구분된다. 판정 없음을 False로 접으면 '게이트가 막았다'가 되고, "
            "True로 접으면 '게이트가 봐 줬다'가 된다. 둘 다 거짓이다."
        ),
    )
    canary_rate: float | None = Field(
        default=None,
        description=(
            "카나리 성공률 **점추정**(`CanaryVerdict.point_estimate`). 참고 표시일 뿐 판정 "
            "근거가 아니다 — 판정은 아래 하한으로 한다(CLAUDE.md 점추정 판정 금지)."
        ),
    )
    canary_lower_bound: float | None = Field(
        default=None,
        description=(
            "카나리 Wilson 단측 **하한**(`CanaryVerdict.wilson_lower`) — 실제 판정 근거값. "
            "`canary_threshold`와 비교하면 대장 행만으로 통과/미달을 재판정할 수 있다."
        ),
    )
    canary_blocked: bool | None = Field(
        default=None,
        description=(
            "카나리 미달로 본배치가 **시작되지 않았는가**. 진행 중 정지(`aborted`)와 다른 "
            "사건이다 — 전자는 시작 전 차단이라 남은 n건이 생성조차 되지 않았다는 뜻이다."
        ),
    )
    canary_advisory: bool | None = Field(
        default=None,
        description=(
            "카나리 판정이 **권고**였는가(n <= canary_size라 막을 본배치가 없던 경우). 판정은 "
            "냈지만 차단력이 없었다는 뜻 — 이 값이 없으면 운영자가 통과 회차를 '게이트가 봐 "
            "줬다'로 오독한다."
        ),
    )
    canary_basis: str | None = Field(
        default=None,
        description=(
            "카나리 표본 기준(MP-02 재회차) — `attempts`=앞머리 시도 canary_size건, `judged`=중복을 "
            "뺀 판정 대상이 canary_size건 모일 때까지. 같은 `canary_rate`라도 기준에 따라 뜻이 "
            "달라진다. None=이 필드 이전 회차(미기록 — 소급 추정 금지)."
        ),
    )
    canary_attempts: int | None = Field(
        default=None,
        ge=0,
        description=(
            "카나리 판정 시점까지 소비한 **시도 수**. attempts 기준이면 canary_size와 같고 judged "
            "기준이면 중복만큼 크다 — 검수 구간을 자를 때 이 값이 카나리의 실제 경계다. "
            "판정이 없었으면 None."
        ),
    )
    aborted: bool | None = Field(
        default=None,
        description=(
            "롤링 불량률 초과로 회차가 조기 중단됐는가. 중단돼도 그 시점까지의 수용분은 "
            "append되므로 `appended > 0`인 중단 회차가 있을 수 있다 — 중단은 폐기가 아니다."
        ),
    )
    abort_reason: str | None = Field(
        default=None,
        description=(
            "중단 사유(관측 불량률·창 크기·임계 포함). 중단이 없으면 None이고, 그 구분은 "
            "`aborted`가 말한다(`aborted=False`+None=중단 없음 / `aborted=None`=미기록)."
        ),
    )
    prompt_cache: dict[str, Any] | None = Field(
        default=None,
        description=(
            "이 회차의 프롬프트 캐시 작동 신호(EOS-99) — `prompt_cache_rates` 산출물 그대로"
            "(적중률·토큰 3종·플래그 상태·상태 어휘). 회차 대장에 싣는 이유는 적중률이 "
            "**회차 간 비교로만 의미를 갖기** 때문이다: 한 회차의 0%는 프리픽스가 짧았을 수도 "
            "있지만, 플래그가 켜진 채 0%가 연속되면 '켰지만 작동 안 함'이 구조 신호가 된다. "
            "None=미기록(이 필드 신설 이전 구행)이고, `state='not_applicable'`은 '측정 "
            "대상이 아니었다'(로컬 경로만 돈 회차)로 0%와 구분된다."
        ),
    )
    cloud_seat: dict[str, Any] | None = Field(
        default=None,
        description=(
            "이 회차의 **좌석 작동 신호**(EOS-111/112 · `seat_operating_rates` 산출물 그대로 — "
            "`selected_seat`·`state`·선언/관측 모델·`observation.declared_vs_served`·재시도). "
            "회차 대장에 싣는 이유는 **대장만으로 '어느 좌석의 회차인가'를 알 수 있어야** "
            "하기 때문이다. 종전에는 이 블록이 stdout 요약에만 실려서(요약은 파이프로 받지 "
            "않으면 사라진다) 대장 행이 좌석을 말하지 못했다 — EOS-121 파일럿 회차에서 실제로 "
            "`cloud_seat: null`이 관측됐고, 좌석 비교가 전부인 측정에서 대장이 좌석을 모르면 "
            "그 회차는 판정 재료가 아니다(2026-09-19 실측). `spec_outcome_counts`(spec 축)와 "
            "**짝**을 이뤄 좌석 × spec 교차 집계를 대장만으로 성립시킨다.\n"
            "\n"
            "미측정과 0의 구분(3상태) — 이 필드를 읽는 규약:\n"
            "  · 필드 자체가 `None` = **미기록**. 이 필드 신설 이전 구행이거나 대장 적재가 "
            "    실패한 회차다. '클라우드가 안 돌았다'가 아니다.\n"
            "  · `state='not_measured'`(`measured=false`) = 이 회차에 `model_name`이 실린 호출이 "
            "    0건이라 **좌석 판정이 정의되지 않는다**. 0%가 아니다.\n"
            "  · `state='none_on_selected_seat'` = 측정은 됐고 선택 좌석의 핀이 **실측 0건**이다"
            "(로컬 전용 회차가 여기 걸린다 — 진짜 0이며 미측정이 아니다).\n"
            "  · `selected_seat='unknown'` + `seat_model_pins=[]` = 설정 판독 자체가 실패한 "
            "    회차다(CLI가 좌석을 미상으로 남긴 경로). 이때의 on/off 계수는 '선택 좌석'을 "
            "    모르는 상태에서 센 값이므로 좌석 판정으로 읽지 않는다."
        ),
    )


def default_round_ledger_path(out_path: Path) -> Path:
    """회차 대장 기본 경로 — 축적 산출물 곁 사이드카 `<out>.rounds.jsonl`(항상 적재).

    genlog(`<out>.genlog.jsonl`)·검수 큐(`<out>.review.jsonl`)와 같은 규약이다. 끄는 옵션을
    두지 않는 이유: 플래그를 잊으면 회차 이력이 조용히 비고, 그러면 연속 무진전 알람이 영원히
    "측정 불가"가 된다 — 알람을 껐는지 아무 일도 없었는지 구분할 수 없는 상태가 된다.
    대장은 `--out`마다 하나라 서로 다른 코퍼스의 회차가 한 창에 섞이지 않는다.
    """
    return out_path.with_suffix(".rounds.jsonl")


def append_round_ledger(path: Path, record: RoundRecord) -> RoundRecord:
    """회차 1행을 대장에 **즉시** append한다(open→기록→flush→close — genlog·검수 큐 동형).

    `recorded_at`이 비어 있으면 append 시각(UTC)으로 스탬프한다. 매체 파생 필드
    `source_line`은 기록하지 않는다(로더가 실제 줄 번호를 주입). 스탬프된 행을 반환한다.
    """
    stamped = (
        record
        if record.recorded_at is not None
        else record.model_copy(update={"recorded_at": datetime.now(UTC)})
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stamped.model_dump_json(exclude={"source_line"}) + "\n")
        handle.flush()
    return stamped


def load_round_ledger(path: Path) -> tuple[list[RoundRecord], list[str]]:
    """대장 JSONL을 읽는다 — (유효 행[줄 번호 주입], 실패 사유[타입명+줄 번호]) 튜플.

    파싱·검증 실패 줄은 삼키지 않고 사유로 수집한다(침묵 실패 금지 — **예외 타입명** + 줄
    번호 + 실패 필드 위치만. 필드 *값*·원문 줄은 넣지 않는다 — `load_review_queue_jsonl`
    동형). 파일 부재는 FileNotFoundError 전파 — "파일 없음"과 "행 0건"은 다르다(미측정≠0).
    """
    entries: list[RoundRecord] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = RoundRecord.model_validate(json.loads(text))
            except ValidationError as exc:
                locs = ",".join(
                    "/".join(str(part) for part in err.get("loc", ())) or "(root)"
                    for err in exc.errors()
                )
                errors.append(f"line {line_no}: ValidationError: fields=[{locs}]")
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"line {line_no}: {type(exc).__name__}")
            else:
                entries.append(parsed.model_copy(update={"source_line": line_no}))
    return entries, errors


@dataclass(frozen=True, slots=True)
class StagnationVerdict:
    """연속 무진전 판정 — 알람 여부와 그 *근거*(관측 회차 수·연속 길이)를 함께 낸다.

    `measured=False`는 "무진전 아님"이 아니라 **잴 것이 없었다**는 뜻이다(대장 행 0). 두 상태를
    같은 색(alarm=False)으로만 두면 "회차를 한 번도 안 돌린 상태"가 "잘 돌고 있는 상태"로
    위장된다 — 그래서 `measured`와 `message`가 그 구분을 항상 말한다.
    """

    window: int
    """알람 임계 — 이 횟수 이상 연속 무진전이면 알람."""

    observed_rounds: int
    """대장에서 읽은 유효 회차 수(분모 — 0이면 measured=False)."""

    consecutive_zero: int
    """최신 회차부터 연속으로 `appended == 0`인 회차 수."""

    alarm: bool
    """알람 발효 여부(measured이고 consecutive_zero >= window일 때만 True)."""

    measured: bool
    """판정 재료가 있었는가 — 대장 유효 행 0이면 False(미측정≠무진전 없음)."""

    message: str
    """사람이 읽는 한 줄 — 알람·정상·측정 불가를 각각 다른 문장으로 말한다."""

    def to_json(self) -> dict[str, Any]:
        """리포트 JSON에 싣는 형태(dataclass → dict — 필드명 그대로)."""
        return {
            "window": self.window,
            "observed_rounds": self.observed_rounds,
            "consecutive_zero": self.consecutive_zero,
            "alarm": self.alarm,
            "measured": self.measured,
            "message": self.message,
        }


def judge_stagnation(
    records: list[RoundRecord],
    *,
    window: int = DEFAULT_STAGNATION_WINDOW,
    load_errors: list[str] | None = None,
) -> StagnationVerdict:
    """대장 이력에서 연속 무진전을 판정한다(순수 — 파일 I/O 0).

    `records`는 대장 파일 순서(append 순 = 시간순)로 들어온다고 본다 — 마지막 원소가 최신
    회차다. 최신부터 거슬러 `appended == 0`이 연속으로 몇 회 이어지는지 세고, 그 길이가
    `window` 이상이면 알람이다.

    `load_errors`가 있으면(대장 일부 줄이 깨짐) 유효 행만으로 판정하되 **메시지에 그 사실을
    명기**한다 — 깨진 줄이 하필 수용 회차였다면 연속 길이가 과대평가되므로, 판정을 조용히
    내리지 않고 근거의 불완전성을 함께 말한다(침묵 실패 금지).

    `window <= 0`은 알람을 상시 참으로 만들어 판정을 무의미하게 만든다 — ValueError로 거부
    한다(변별력 없는 게이트를 인자로 만들 수 없게).
    """
    if window <= 0:
        raise ValueError(f"stagnation window는 1 이상이어야 한다(받은 값 {window}).")

    errors = load_errors or []
    observed = len(records)
    if observed == 0:
        return StagnationVerdict(
            window=window,
            observed_rounds=0,
            consecutive_zero=0,
            alarm=False,
            measured=False,
            message=(
                "측정 불가 — 회차 대장에 유효 행이 0건이다(무진전이 아니라 잰 것이 없다)."
                + (f" 로드 실패 {len(errors)}행." if errors else "")
            ),
        )

    consecutive = 0
    for record in reversed(records):
        if record.appended > 0:
            break
        consecutive += 1

    alarm = consecutive >= window
    broken = f" (대장 로드 실패 {len(errors)}행 — 연속 길이가 과대평가일 수 있다)" if errors else ""
    if alarm:
        message = (
            f"연속 무진전 알람 — 최근 {consecutive}회차 연속으로 코퍼스에 신규 행이 0건이다"
            f"(임계 {window}회차·관측 {observed}회차). 생성기·게이트·dedup 중 어디서 막히는지 "
            f"회차 리포트의 작동한 비율 분포로 확인하라.{broken}"
        )
    else:
        message = (
            f"진전 관측 — 연속 무진전 {consecutive}회차(임계 {window} 미만·관측 {observed}회차)."
            f"{broken}"
        )
    return StagnationVerdict(
        window=window,
        observed_rounds=observed,
        consecutive_zero=consecutive,
        alarm=alarm,
        measured=True,
        message=message,
    )


# ──────────────────────────────────────────────────────────────────────────
# 좌석 작동 신호 (EOS-111) — "셀렉터가 지목한 좌석이 실제로 돌았는가"
#
# `PromptCacheTally`/`prompt_cache_rates`와 **동형**이다(두 벌 산식 금지): 같은
# genlog 행에서 모으고, 같은 미측정 규약(`measured`·`unmeasured_reason`·`state`)을
# 쓰며, 리포트와 대장에 같은 dict를 싣는다.
#
# 왜 필요한가(실사고 2026-09-18): OpenRouter 좌석으로 돌린 저작 회차가 `EXIT=0`·5/5
# 저장으로 끝났는데 **그 좌석이 실제로 서빙했는지 요약만으로 판정할 수 없었다**.
# `prompt_cache`의 `calls_with_cache_telemetry: 0`은 "이 provider가 캐시 필드를
# 노출하지 않는다"와 "LOCAL 경로만 돌았다" 양쪽에서 같은 값이라 변별력이 0이었고,
# genlog 사이드카를 따로 열어야 알 수 있었다. 요약이 스스로 말했다면 왕복이 없었다.
# ──────────────────────────────────────────────────────────────────────────

SEAT_STATES: Final[frozenset[str]] = frozenset(
    {"not_measured", "all_on_selected_seat", "none_on_selected_seat", "mixed"}
)
"""좌석 작동 상태 어휘 — 측정 가능성을 먼저 보고, 그다음에 좌석 일치를 본다."""


@dataclass(slots=True, frozen=True)
class SeatTally:
    """회차 안 genlog 행에서 모은 좌석 원장(불변·순수·파일 I/O 0).

    `observe`는 **새 인스턴스를 돌려준다**(`PromptCacheTally` 동형) — 싱크가 회차 도중
    누적하되 중간 상태가 다른 곳에서 조용히 바뀌지 않게 한다.

    **`model_name`이 없는 행은 분모에 넣지 않는다.** 미기록과 "다른 모델이 돌았다"를
    구분하는 것이 이 집계의 급소다 — 미기록 행을 '좌석 밖'으로 계상하면 기록이 빠진
    회차가 "좌석이 안 돌았다"로 위장된다(미측정 ≠ 0).
    """

    calls_total: int = 0
    """관측한 genlog 행 수(전체) — 분모가 아니라 *관측 규모*다."""

    calls_with_model_name: int = 0
    """`model_name`이 실린 행 수 — 이 값이 0이면 좌석 판정이 정의되지 않는다."""

    by_model: tuple[tuple[str, int], ...] = ()
    """(모델명, 건수) 오름차순 튜플 — dict가 아니라 튜플인 것은 불변성 때문이다."""

    succeeded: int = 0
    """`success is True`인 행 수."""

    failed: int = 0
    """`success is False`인 행 수. `success`가 None인 행은 어느 쪽도 아니다."""

    cost_usd_total: float = 0.0
    """`cost_usd`가 실린 행의 합 — **단가 곱셈이며 청구서 미대조**다(EOS-111 범위 밖)."""

    calls_with_cost: int = 0
    """`cost_usd`가 실린 행 수 — 합이 0.0인 것과 '아무도 안 실었다'를 구분한다."""

    # ── 관측 축 (EOS-112) — 위 필드들이 *선언값*(설정이 지목한 모델)을 센다면 아래는
    # *관측값*(응답이 온 모델)을 센다. 둘을 같은 원장에서 세는 이유는 **대조가 목적**이라
    # 따로 순회하면 같은 행을 두 번 읽으며 갈라질 수 있기 때문이다.
    calls_with_served_model: int = 0
    """`served_model`이 실린 행 수 — 0이면 관측 자체가 없었다(어긋남 0건이 아니다)."""

    by_served_model: tuple[tuple[str, int], ...] = ()
    """(관측 모델명, 건수) 오름차순 튜플 — `by_model`(선언)과 짝을 이룬다."""

    declared_served_comparable: int = 0
    """선언·관측이 **둘 다** 실린 행 수 — 대조의 분모. 한쪽만 있으면 비교가 성립하지 않는다."""

    declared_served_differs: int = 0
    """대조 가능한 행 중 두 값이 다른 행 수 — 분자."""

    differing_pairs: tuple[tuple[str, str, int], ...] = ()
    """(선언값, 관측값, 건수) 오름차순 — 어긋남의 *내용*. 건수만으로는 별칭 해소와 진짜
    폴백을 구분할 수 없어서 쌍 자체를 남긴다."""

    calls_with_retries: int = 0
    """`retries`가 실린 행 수(계측된 행). Anthropic·Ollama 경로는 여기 들어오지 않는다."""

    retries_total: int = 0
    """계측된 행의 재시도 합."""

    calls_with_any_retry: int = 0
    """재시도가 1회 이상 일어난 행 수 — 합이 큰 것이 한 행 탓인지 여러 행 탓인지 가른다."""

    def observe(
        self,
        *,
        model_name: str | None,
        success: bool | None,
        cost_usd: float | None,
        served_model: str | None = None,
        retries: int | None = None,
    ) -> SeatTally:
        """genlog 행 1건을 반영한 새 원장을 돌려준다(원본 불변).

        None은 **더하지 않는다**(0으로 접지 않는다) — 미기록과 실측 0의 구분이 이 집계의
        전부이기 때문이다.
        """
        counts = dict(self.by_model)
        with_model = self.calls_with_model_name
        if model_name:
            counts[model_name] = counts.get(model_name, 0) + 1
            with_model += 1
        served_counts = dict(self.by_served_model)
        with_served = self.calls_with_served_model
        if served_model:
            served_counts[served_model] = served_counts.get(served_model, 0) + 1
            with_served += 1
        # 대조는 **둘 다 실린 행에서만** 성립한다 — 한쪽이 없는 행을 '일치'로도 '어긋남'
        # 으로도 계상하면 미관측이 판정으로 둔갑한다(모른다 ≠ 아니다).
        comparable = self.declared_served_comparable
        differs = self.declared_served_differs
        pairs = {(d, s): n for d, s, n in self.differing_pairs}
        if model_name and served_model:
            comparable += 1
            if model_name != served_model:
                differs += 1
                key = (model_name, served_model)
                pairs[key] = pairs.get(key, 0) + 1
        return replace(
            self,
            calls_total=self.calls_total + 1,
            calls_with_model_name=with_model,
            by_model=tuple(sorted(counts.items())),
            succeeded=self.succeeded + (1 if success is True else 0),
            failed=self.failed + (1 if success is False else 0),
            cost_usd_total=self.cost_usd_total + (cost_usd if cost_usd is not None else 0.0),
            calls_with_cost=self.calls_with_cost + (1 if cost_usd is not None else 0),
            calls_with_served_model=with_served,
            by_served_model=tuple(sorted(served_counts.items())),
            declared_served_comparable=comparable,
            declared_served_differs=differs,
            differing_pairs=tuple((d, s, n) for (d, s), n in sorted(pairs.items())),
            # `retries`는 None(미계측)과 0(계측·재시도 없음)이 다른 사실이다. None은
            # 분모에도 들어가지 않는다 — 들어가면 계측 없는 경로가 '재시도 0%'로 보인다.
            calls_with_retries=self.calls_with_retries + (1 if retries is not None else 0),
            retries_total=self.retries_total + (retries if retries is not None else 0),
            calls_with_any_retry=(
                self.calls_with_any_retry + (1 if retries is not None and retries > 0 else 0)
            ),
        )


def seat_operating_rates(
    tally: SeatTally,
    *,
    selected_seat: str,
    seat_model_pins: tuple[str, ...],
) -> dict[str, Any]:
    """회차의 좌석 '작동한 비율' + 판정(순수·파일 I/O 0).

    `selected_seat`는 이 회차가 돌 때의 `settings.cloud_provider`, `seat_model_pins`는
    그 좌석의 모델 핀들(`l3/providers/factory.cloud_model_pins()`)이다. 관측 모델이 그
    핀에 속하면 "선택한 좌석이 돌았다", 아니면 "다른 것이 돌았다"(대개 LOCAL)이다.

    **이 판정은 선언값 기반이다**(`ARCH-58`): genlog의 `model_name`은 *설정이 지목한*
    모델이지 *응답이 온* 모델이 아니다. 따라서 provider 측 대체·폴백은 이 신호로 보이지
    않는다 — 그 축은 `EOS-112`가 소유한다. 여기서 답하는 질문은 "라우팅이 클라우드로
    갔고 그 좌석이 선택한 것과 같은가"까지다.

    상태 어휘(`SEAT_STATES`):
      - `not_measured` — `model_name`이 실린 행 0건. 좌석 판정 불가(0%가 아니다).
      - `all_on_selected_seat` — 측정된 행이 전부 선택 좌석의 핀이다.
      - `none_on_selected_seat` — 측정된 행 중 선택 좌석의 핀이 **0건**. 셀렉터를
        openrouter로 두고도 LOCAL만 돈 회차가 여기 걸린다 — 이 함수가 존재하는 이유다.
        회차가 원래 LOCAL로 라우팅될 조건이었다면 정상이며, 그 판단은 읽는 사람 몫이다
        (도구는 사실만 적는다).
      - `mixed` — 일부만 선택 좌석. 클라우드·로컬 혼재 회차.
    """
    pins = frozenset(seat_model_pins)
    on_seat = sum(count for model, count in tally.by_model if model in pins)
    off_seat = tally.calls_with_model_name - on_seat
    measured = tally.calls_with_model_name > 0
    unmeasured_reason: str | None = None
    if not measured:
        state = "not_measured"
        unmeasured_reason = (
            f"model_name이 실린 호출 0건(관측 {tally.calls_total}건) — 좌석 판정이 "
            "정의되지 않는다. '선택 좌석이 안 돌았다'가 아니다(미측정)."
        )
    elif off_seat == 0:
        state = "all_on_selected_seat"
    elif on_seat == 0:
        state = "none_on_selected_seat"
    else:
        state = "mixed"
    return {
        "selected_seat": selected_seat,
        "seat_model_pins": list(seat_model_pins),
        "calls_total": tally.calls_total,
        "calls_with_model_name": tally.calls_with_model_name,
        "calls_on_selected_seat": on_seat,
        "calls_off_selected_seat": off_seat,
        "observed_models": {model: count for model, count in tally.by_model},
        "succeeded": tally.succeeded,
        "failed": tally.failed,
        # 비용은 **단가 곱셈이며 청구서 미대조**다(EOS-111 acceptance ⑥ — 정확도 향상은
        # 이 태스크 밖). 실은 행이 0건이면 합 0.0을 '0원 확정'으로 읽지 않도록 건수를 함께 낸다.
        "cost_usd_total": tally.cost_usd_total if tally.calls_with_cost else None,
        "calls_with_cost": tally.calls_with_cost,
        "cost_note": "단가 곱셈·청구서 미대조",
        "measured": measured,
        "unmeasured_reason": unmeasured_reason,
        "declared_not_observed": (
            "위 state·on/off 판정은 선언값(model_name · 설정 유래 · ARCH-58) 기반이다. "
            "응답에서 읽은 관측값은 아래 observation 블록에 따로 싣는다(EOS-112) — 두 값을 "
            "한 필드로 합치지 않는 이유는 provider가 모델 식별자를 안 돌려주는 회차에서 "
            "'관측 실패'가 '선언값과 일치'로 위장되기 때문이다."
        ),
        "observation": _observation_block(tally),
        "state": state,
    }


_DIFFERING_PAIR_LIMIT: Final[int] = 20
"""요약에 싣는 (선언, 관측) 어긋남 쌍의 상한 — 넘치면 잘렸다는 사실을 함께 적는다."""


def _observation_block(tally: SeatTally) -> dict[str, Any]:
    """'누가 실제로 답했나' 축 (EOS-112) — 선언 축과 **분리된** 블록으로 낸다.

    세 가지를 각각 말한다:
      ① **관측 규모** — `served_model`이 실린 행 수. 0이면 어긋남 0건이 아니라 *관측
         자체가 없었다*이다(provider가 모델 식별자를 안 싣거나 호출이 없었던 회차).
      ② **대조 결과** — 선언·관측이 둘 다 있는 행에서만 비교한다. `differs`가 0보다 크면
         provider 측 대체·폴백·프록시 라우팅이 **일어났을 수 있다**. 다만 별칭→버전 해소
         (`claude-sonnet-4-6` → 날짜 붙은 ID, `qwen2-math` → `qwen2-math:7b`)도 같은
         차이로 나타나므로 이것은 *판정*이 아니라 **볼 자리**다 — 그래서 건수만이 아니라
         쌍 자체를 싣는다(쌍을 보면 사람이 한눈에 가른다). 상시 발화하는 경보로 만들면
         사람이 꺼 버리므로 boolean 알람을 두지 않는다.
      ③ **재시도** — 재시도는 측정을 가린다. 계측된 행 수를 분모로 함께 내어, 합 0이
         '재시도 없었다'인지 '아무도 계측 안 했다'인지 구분되게 한다.
    """
    pairs = [
        {"declared": declared, "served": served, "count": count}
        for declared, served, count in tally.differing_pairs[:_DIFFERING_PAIR_LIMIT]
    ]
    return {
        "calls_with_served_model": tally.calls_with_served_model,
        "observed_models": {model: count for model, count in tally.by_served_model},
        "declared_vs_served": {
            "comparable": tally.declared_served_comparable,
            "matched": tally.declared_served_comparable - tally.declared_served_differs,
            "differs": tally.declared_served_differs,
            "differing_pairs": pairs,
            "differing_pairs_truncated": len(tally.differing_pairs) > _DIFFERING_PAIR_LIMIT,
            "note": (
                "차이가 곧 이상은 아니다 — 별칭→버전 해소도 같은 차이로 나타난다. "
                "쌍을 보고 사람이 가른다(자동 판정 아님)."
            ),
        },
        "retries": {
            "calls_with_retries_measured": tally.calls_with_retries,
            # 계측 행이 0건이면 합을 0으로 내지 않는다 — '재시도 없었다'로 읽히기 때문이다.
            "retries_total": tally.retries_total if tally.calls_with_retries else None,
            "calls_with_any_retry": (
                tally.calls_with_any_retry if tally.calls_with_retries else None
            ),
            "note": (
                "None=이 회차에 재시도를 계측한 호출이 0건(Anthropic SDK·Ollama는 우리 "
                "전송기를 타지 않아 카운터가 없다). 0=계측했고 재시도 없었다."
            ),
        },
    }
