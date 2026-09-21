"""배치 안전장치 — 카나리 게이트 + 롤링 불량률 중단 (EOS-95).

**왜 필요한가**: 이 저장소에는 *건별* 게이트(수용 게이트 4종)와 *사후* 게이트
(`qa_pipeline`·`corpus_reverify`)는 있으나 **배치가 도는 도중에 멈추는 장치가 없었다** —
배치 루프가 전부 `for _ in range(n)`이고 누적 통계를 보고 `break`하지 않는다. 그래서
결함이 대량 복제된 *뒤에야* 사후 게이트가 발견한다. 콘텐츠 대량 생산 국면에서 이것은
12월 판정 입력을 통째로 오염시킨다 — 출처는 2026-09-05 갭 리뷰(설계서 대조) §6 G-1이다
(`docs/reviews/eos_micro_project_orchestration_v1_gap_review_2026-09-05.md`).

**이 모듈은 순수하다** — I/O·전역 상태·시간 의존이 없다. 판정 산술만 소유하고,
생성·저장·종료코드는 호출자(배치 루프와 CLI)가 한다. 그래야 결함 주입 테스트가
실제 생성 없이 변별력을 실측할 수 있다.

## 판정은 점추정이 아니라 Wilson 단측 하한이다

CLAUDE.md 검증 권위: *"게이트 판정은 항상 CLI exit 0/1(Wilson 단측 경계) — 점추정·인상
판정 금지."* 카나리처럼 표본이 작을 때 점추정은 과신이다. 실측(2026-09-05):

    30/30 (만점) → 점추정 100.0% · Wilson 95% 하한 **91.7%**
    29/30        → 점추정  96.7% · Wilson 95% 하한 **86.4%**

그래서 **n=30에 임계 0.95는 만점을 받아도 통과할 수 없는 명세**다(91.7% < 95%). 참값
95%를 95% 신뢰로 입증하려면 전건 통과 n≥60(→95.7%)이 필요하다. 2026-09-05 Kiki 결정으로
**임계 0.90 + n=30**을 채택했다 — 생성·검수 비용이 2배가 되는 n=60 대신이다.

    임계 0.90에서 30/30(91.7%)만 통과하고 29/30(86.4%)은 탈락한다 — 사실상 만점 요구다.
    관대한 값이 아니다.

**n 또는 임계를 바꾸려면 이 계산을 다시 하고 근거를 남긴다**(`DEFAULT_CANARY_SIZE`·
`DEFAULT_CANARY_THRESHOLD`를 고치는 커밋은 위 표도 함께 갱신한다).

## 집행 지점 — 어느 배치 루프가 이 게이트를 경유하는가 (정본화 ≠ 집행)

**이 모듈이 존재한다는 것과 배치가 이걸 부른다는 것은 다르다.** 현행 배치 루프 3종의
경유 여부는 아래가 전부다(2026-09-06 실측 · `test_batch_safety_wiring.py`가 동결):

**① `harness/problem_corpus_accumulate.py::run_corpus_accumulate` — 경유한다.**
카나리 관문과 롤링 중단 둘 다. CLI(`main`)가 게이트 판정을 exit 1로 낸다.

**② `l3/equivalent/orchestrator.py::run_batch` — 경유하지 않는다.**
L3(생성 계층)이라 harness를 import할 수 없다(계층 역참조). 이 좌석에 게이트를 두려면
순수 부품을 L3로 내리는 별도 판단이 필요하다.

**③ `harness/problem_corpus_batch.py::run_batch` — 경유하지 않는다.**
②를 감싼 밴드별 래퍼다. 밴드마다 독립 호출이라 "배치 전체의 롤링 창"이 자연스럽게
정의되지 않는다 — 창을 밴드 안에 둘지 가로질러 둘지가 설계 결정이며 본 태스크 범위 밖이다.

즉 **결정론 저작 배치(`problem_corpus_batch`)는 아직 보호받지 않는다.** 그것을 "보호
있음"으로 읽으면 안 된다. 다만 그 경로는 배치 35/36이 LLM 0의 결정론 생성이라 F1·F2류
실패가 구조적으로 거의 나지 않는 구간이고, 라이브 LLM 축적 경로(보호 대상)가 12월 검증의
실제 위험 구간이다 — 그래서 이 순서로 배선했다.

## 기본 경로가 실제로 판정하는가 (2026-09-06 실측 사고)

**보호를 켰다고 선언하는 것과 그 보호가 기본 설정에서 판정을 내리는 것은 다르다.**

초판은 `DEFAULT_CANARY_SIZE=30` · `DEFAULT_ABORT_WINDOW=50`으로 두고 롤링 판정 시작점을
창 크기와 같게 묶었다. 그런데 이 CLI의 기본 `--n`은 **20**이다. 결과:

    n=20 <= 카나리 30  → 막을 본배치가 없으므로 카나리 미판정
    n=20 <  창 50      → 최소 표본 미달이라 롤링 미판정
    → 전건 실패 20건인데 canary=None · blocked=False · aborted=False (실측)

즉 **두 안전장치가 "기본 ON"이라고 적혀 있는 채로 기본 경로에서 아무것도 하지 않았다.**
이것은 CLAUDE.md가 지목한 "상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지"의
전형이다. 뮤테이션 배터리가 이걸 놓친 이유도 분명하다 — 테스트가 매번 게이트 인자를
명시로 넘겨 **기본 설정을 한 번도 실행하지 않았다**(Codex P1이 지적).

대책 두 축:
- 롤링 판정 시작점을 창 크기에서 분리(`DEFAULT_ABORT_MIN_SAMPLES=10`) — 기본 경로가 판정한다
- 카나리가 *막을* 수 없는 크기에서도 **판정 자체는 내고 리포트에 싣는다**(권고 판정) —
  차단은 못 해도 "몇 건 중 몇 건이었는지"는 운영자에게 보인다
- 회귀 가드: `test_default_configuration_actually_decides`가 **기본 인자만으로** 호출해
  안전 판정이 실재하는지 확인한다

## 측정 실패는 통과가 아니다

시도 0건은 "불량 0% 통과"가 아니라 **측정 실패**다(CLAUDE.md 2026-08-22 — 측정·수집
도구를 성공 경로만 보고 설계 금지). `evaluate_canary(trials=0)`은 `passed=False` +
`measurement_failed=True`를 낸다. 호출자는 이 둘을 구별해 보고해야 한다 — 게이트 탈락과
측정 실패는 대응이 다르다(전자는 생성 품질, 후자는 파이프라인 고장).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from whymath_backend.harness.wilson import wilson_lower_bound

__all__ = [
    "ACCEPTED_STATUSES",
    "NEUTRAL_STATUSES",
    "CanaryVerdict",
    "DEFAULT_ABORT_MIN_SAMPLES",
    "DEFAULT_ABORT_THRESHOLD",
    "DEFAULT_ABORT_WINDOW",
    "DEFAULT_CANARY_CONFIDENCE",
    "DEFAULT_CANARY_SIZE",
    "DEFAULT_CANARY_THRESHOLD",
    "RollingFailureWindow",
    "evaluate_canary",
    "is_accepted_status",
    "is_neutral_status",
]

#: 수용으로 치는 `GenerationOutcome.status` — `run_corpus_accumulate`의 기준과 동일 집합.
#: 허용목록이다(새 status가 생겨도 자동으로 성공에 들지 않는다 — fail-closed).
ACCEPTED_STATUSES = frozenset({"accepted_stored", "accepted"})

#: **성공도 불량도 아닌** status — 판정 분모에서 통째로 제외한다.
#:
#: `rejected_duplicate`가 여기 있는 이유: 중복은 *결함*이 아니라 dedup이 제대로 일한
#: 결과다. 이 게이트들이 막으려는 것은 **결함의 대량 복제**이지 중복 생성이 아니다.
#: 중복을 불량으로 세면 "시드와 구조가 겹치는 앞부분 → 뒤에서 신선한 후보" 같은 정상
#: 축적 회차가 앞부분만 보고 중단된다(2026-09-06 실측: 기존 회귀 테스트가 이걸 잡았다).
#:
#: "새 문항이 안 쌓인다"는 별개 축이고 이미 다른 장치가 본다 — 회차 무진전 알람(exit 2)과
#: `appended == 0`(exit 1). 한 신호에 두 가지 뜻을 얹지 않는다.
NEUTRAL_STATUSES = frozenset({"rejected_duplicate"})

#: 카나리 표본 수 · 통과 임계 · 신뢰수준. 근거는 모듈 docstring의 실측 표.
DEFAULT_CANARY_SIZE = 30
DEFAULT_CANARY_THRESHOLD = 0.90
DEFAULT_CANARY_CONFIDENCE = 0.95

#: 롤링 창 크기와 불량률 임계 — 본배치 진행 중 감시.
DEFAULT_ABORT_WINDOW = 50
DEFAULT_ABORT_THRESHOLD = 0.30
#: 롤링 판정을 시작하는 최소 관측 수. **창 크기와 분리한다** — 창은 *얼마나 뒤를 보는가*이고
#: 이 값은 *언제부터 판정하는가*다. 둘을 같은 값으로 묶으면 창보다 짧은 배치가 통째로 무판정이
#: 된다(2026-09-06 실측 사고 — 아래 "기본 경로가 판정하는가" 참조).
DEFAULT_ABORT_MIN_SAMPLES = 10


def is_accepted_status(status: str) -> bool:
    """`status`가 수용인지 — 허용목록 판정(모르는 값은 불수용)."""
    return status in ACCEPTED_STATUSES


def is_neutral_status(status: str) -> bool:
    """판정 분모에서 제외할 status인지 — 성공도 불량도 아닌 것(중복 등)."""
    return status in NEUTRAL_STATUSES


@dataclass(frozen=True, slots=True)
class CanaryVerdict:
    """카나리 판정 — 통과 여부와 *그 근거 수치 전부*.

    `passed`만 보고 넘어가면 왜 막혔는지가 사라지므로 점추정·하한·임계를 함께 싣는다.
    `measurement_failed`는 게이트 탈락과 **다른 사건**이다(모듈 docstring 참조).
    """

    passed: bool
    trials: int
    successes: int
    point_estimate: float
    wilson_lower: float
    threshold: float
    confidence: float
    measurement_failed: bool
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "trials": self.trials,
            "successes": self.successes,
            "point_estimate": round(self.point_estimate, 4),
            "wilson_lower": round(self.wilson_lower, 4),
            "threshold": self.threshold,
            "confidence": self.confidence,
            "measurement_failed": self.measurement_failed,
            "reason": self.reason,
        }


def evaluate_canary(
    statuses: Iterable[str],
    *,
    threshold: float = DEFAULT_CANARY_THRESHOLD,
    confidence: float = DEFAULT_CANARY_CONFIDENCE,
) -> CanaryVerdict:
    """카나리 회차의 outcome status들로 본배치 진행 가부를 판정한다.

    통과 조건은 **Wilson 단측 하한 ≥ threshold**다(점추정이 아니다 — 모듈 docstring).
    시도 0건은 통과가 아니라 `measurement_failed`로 판정한다.

    Args:
        statuses: 카나리 회차가 낸 `GenerationOutcome.status` 나열.
        threshold: 통과에 요구하는 Wilson 하한. 기본 0.90(2026-09-05 Kiki 결정).
        confidence: Wilson 단측 신뢰수준. 기본 0.95.

    Returns:
        `CanaryVerdict` — `passed`가 False면 호출자가 본배치를 **시작하지 않는다**.
    """
    # 중립(중복 등)은 분모에서 제외한다 — 품질 판정이지 생산량 판정이 아니다.
    materialized = [status for status in statuses if not is_neutral_status(status)]
    trials = len(materialized)
    if trials == 0:
        # 시도 0건 = 측정 실패. "불량 0%"로 위장하면 파이프라인 고장이 통과로 보인다.
        return CanaryVerdict(
            passed=False,
            trials=0,
            successes=0,
            point_estimate=0.0,
            wilson_lower=0.0,
            threshold=threshold,
            confidence=confidence,
            measurement_failed=True,
            reason=(
                "측정 실패: 카나리 판정 대상 0건 — 통과율을 계산할 수 없다(불량 0% 아님). "
                "전건이 중복 등 중립 status면 여기 걸린다"
            ),
        )

    successes = sum(1 for status in materialized if is_accepted_status(status))
    point = successes / trials
    lower = wilson_lower_bound(successes, trials, confidence)
    passed = lower >= threshold
    if passed:
        reason = (
            f"카나리 통과: {successes}/{trials} · Wilson {confidence:.0%} 하한 "
            f"{lower:.1%} ≥ 임계 {threshold:.0%}"
        )
    else:
        # 사유는 **사실만** 말한다 — "본배치 차단" 같은 *결과*는 호출자가 정한다(같은 판정이
        # 차단일 수도, 차단력 없는 권고일 수도 있다). 순수 모듈이 결과를 단정하면 권고 경로에서
        # 거짓말이 된다(2026-09-06 실측).
        reason = (
            f"카나리 미달: {successes}/{trials}(점추정 {point:.1%}) · Wilson "
            f"{confidence:.0%} 하한 {lower:.1%} < 임계 {threshold:.0%}"
        )
    return CanaryVerdict(
        passed=passed,
        trials=trials,
        successes=successes,
        point_estimate=point,
        wilson_lower=lower,
        threshold=threshold,
        confidence=confidence,
        measurement_failed=False,
        reason=reason,
    )


class RollingFailureWindow:
    """최근 N건의 불량률을 보고 중단을 판정하는 슬라이딩 창.

    **왜 곧바로 판정하지 않는가**: 첫 1건이 불량이면 순간 불량률은 100%다. 관측이 몇 건
    없을 때 판정하면 정상 배치도 초반 1~2건 때문에 멈춘다 — 그런 장치는 보호가 아니라
    소음이다. 그래서 `min_samples` 이상 관측한 뒤에만 판정한다.

    **창 크기와 `min_samples`는 다른 축이다** — 창은 *얼마나 뒤를 보는가*(lookback),
    `min_samples`는 *언제부터 판정하는가*다. 둘을 묶으면(초판이 그랬다) 창보다 짧은 배치가
    통째로 무판정이 되고, 기본 창 50 · 기본 `--n` 20 조합에서 **기본 경로 전체가 무판정**이
    된다. 그래서 기본은 `min(window, DEFAULT_ABORT_MIN_SAMPLES)`다.

    **남는 한계(명시)**: `min_samples`(기본 10)보다 짧은 배치는 여전히 판정되지 않는다.
    그 구간은 표본이 너무 적어 어떤 비율 판정도 의미가 없다 — 카나리도 같은 이유로 못 막는다.
    10건 미만 배치는 **구조적으로 게이트 밖**이며, 그것을 보호로 착각하면 안 된다.

    점추정을 쓰는 이유는 카나리와 목적이 다르기 때문이다 — 카나리는 *진행 가부의 게이트*
    라 보수적 하한이 맞지만, 롤링은 *이미 도는 배치를 멈추는 비상정지*라 반응성이 필요하다.
    Wilson 상한을 쓰면 초기 구간에서 과하게 민감해져 정상 배치를 멈춘다.
    """

    __slots__ = ("_window", "_min_samples", "_threshold", "_observed", "_failures_total")

    def __init__(
        self,
        *,
        window: int = DEFAULT_ABORT_WINDOW,
        threshold: float = DEFAULT_ABORT_THRESHOLD,
        min_samples: int | None = None,
    ) -> None:
        """`min_samples` 기본값은 `min(window, DEFAULT_ABORT_MIN_SAMPLES)`다.

        창 크기를 그대로 쓰지 **않는** 이유: 기본 창 50에 그렇게 하면 50건 미만 배치가
        한 번도 판정되지 않는다 — 그리고 이 CLI의 기본 `--n`은 20이라 **기본 경로 전체가
        무판정**이 된다(2026-09-06 Codex P1 실측). 창은 lookback이고 이 값은 판정 시작점이니
        분리해야 한다.
        """
        if window <= 0:
            raise ValueError(f"window must be > 0, got {window}")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {threshold}")
        self._window: deque[bool] = deque(maxlen=window)
        self._min_samples = (
            min(window, DEFAULT_ABORT_MIN_SAMPLES) if min_samples is None else min_samples
        )
        self._threshold = threshold
        self._observed = 0
        self._failures_total = 0

    @property
    def window_size(self) -> int:
        return self._window.maxlen or 0

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def observed(self) -> int:
        """지금까지 창에 넣은 총 건수(창 밖으로 밀려난 것 포함)."""
        return self._observed

    @property
    def failures_total(self) -> int:
        """지금까지 관측한 누적 불량 건수(창 밖 포함) — 리포트용."""
        return self._failures_total

    def observe(self, *, failed: bool) -> None:
        """1건 관측. `failed=True`가 불량이다."""
        self._window.append(failed)
        self._observed += 1
        if failed:
            self._failures_total += 1

    def observe_status(self, status: str) -> bool:
        """`GenerationOutcome.status` 1건 관측 — 수용이 아니면 불량으로 친다.

        **중립 status(중복 등)는 관측하지 않는다**(분모에서 제외 · `NEUTRAL_STATUSES` 참조).
        관측했으면 True, 중립이라 건너뛰었으면 False를 돌려준다.
        """
        if is_neutral_status(status):
            return False
        self.observe(failed=not is_accepted_status(status))
        return True

    def rate(self) -> float:
        """현재 창의 불량률. 창이 비어 있으면 0.0(판정에는 쓰이지 않는다)."""
        if not self._window:
            return 0.0
        return sum(1 for failed in self._window if failed) / len(self._window)

    def should_abort(self) -> bool:
        """지금 중단해야 하는가 — 창이 `min_samples` 이상 찼고 불량률이 임계 **초과**."""
        if len(self._window) < self._min_samples:
            return False
        return self.rate() > self._threshold

    def abort_reason(self) -> str:
        """중단 사유 문자열 — 관측 불량률·창 크기·임계를 전부 싣는다(조용한 중단 금지)."""
        return (
            f"롤링 불량률 초과: 최근 {len(self._window)}건 중 불량률 {self.rate():.1%} > "
            f"임계 {self._threshold:.0%} (누적 관측 {self._observed}건·불량 "
            f"{self._failures_total}건) — 배치 중단"
        )

    def to_json(self) -> dict[str, object]:
        return {
            "window_size": self.window_size,
            "min_samples": self._min_samples,
            "threshold": self._threshold,
            "observed": self._observed,
            "failures_total": self._failures_total,
            "current_rate": round(self.rate(), 4),
        }
