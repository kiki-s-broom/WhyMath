"""활성 오개념 *가설 세트* — 감쇠·강화·ε-규칙(순수 결정 로직).

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4 **2단계**. WH-1(소크라테스
튜터링 하네스) 2단계 = "**활성 가설 세트(감쇠·ε-규칙)** + evidence_links(개인정보 스키마)".
본 모듈은 그 중 *핵심 결정 로직*만 담는 순수 좌석이다(calibration/transfer 슬라이스와 동일한
순수 함수 스타일). `match_misconception`/`MisconceptionMatch`(매처 결과) 위에 구축한다 —
매칭 *알고리즘*은 전혀 건드리지 않고, 이미 만들어진 매치를 *가설*로 누적·관리한다.

핵심 원칙(CLAUDE.md "모든 오답은 *오개념 후보* 분석 시도"·절대 금기 "학생을 정서적으로
낙인 금지"):
  - 오개념은 학생에게 붙는 *영속 라벨*이 아니라 **가설**(후보)일 뿐이다. 그래서 가설 신뢰는
    *증거가 없으면 시간/턴에 따라 감쇠*(`decay`)하고, 임계 미만이면 *가지치기*해 stale
    가설을 정리한다. 한 번 의심된 오개념이 영원히 따라다니지 않게 하는 게 핵심(낙인 방지).
  - 새 증거(`MisconceptionMatch`)가 오면 해당 가설을 *강화*(`reinforce`)한다(단조 증가).
  - 개입 대상 선택은 **ε-규칙**(`select_focus`) — 대부분 최상위 가설을 보되 가끔 차순위를
    *탐색*해 1위 고착(오진단 고정)을 깬다.

**순수·결정론**: DB·provider·LLM·전역 상태를 *모른다*. 입력 가설/매치 시퀀스와 스칼라만으로
결정되고 입력을 변형하지 않는다(`MisconceptionHypothesis`는 frozen·항상 새 리스트 반환).
ε-규칙의 무작위성은 *주입된 `random.Random`*으로만 발생해(전역 `random` 금지) 시드 rng로
완전 결정론 테스트가 가능하다. R-S 보상해킹(탐색을 보상으로 악용) 아님 — 단순 가설 갱신 장치.

**정직 스코프(후속)**: 본 슬라이스는 *순수 결정 로직만*이다. 다음은 모두 **후속 슬라이스**다 —
  · 영속: `misconception_hypothesis` 테이블·repository·alembic 마이그레이션(이번 마이그레이션 0).
  · `evidence_links` 개인정보 스키마(학생 풀이 증거 연결·암호화·동의·PIPA 권한 매트릭스).
  · coach/intervention 파이프라인 결선(가설→개입 발화 자동 연결).
  · 진단-실제 오개념 *일치율* 게이트 측정(LIVE per-user ground-truth는 데이터 기반 미비).
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.misconception.models import MisconceptionMatch

# 설계 §8.4 2단계 고정 상수 — 파라미터화하되 기본값은 설계 의도(stale 가설 정리)를 따른다.
_HALF_LIFE_TURNS = 5
"""감쇠 반감기(턴). 증거 없이 이 턴 수가 지나면 가설 신뢰가 절반으로 — 오개념은 영속
라벨이 아니므로 점진 하락시켜 stale 가설을 자연 정리한다."""

_PRUNE_THRESHOLD = 0.1
"""가지치기 임계. 감쇠로 confidence가 이 값 *미만*이 된 가설은 제거 — 노이즈 가설을
무한 누적하지 않는다(낙인 방지·세트 위생)."""

_DEFAULT_EPSILON = 0.1
"""ε-규칙 탐색 확률. 이 확률로 최상위 외 차순위 가설을 *탐색*해 1위 고착(오진단 고정)을
깬다. 나머지(1-ε)는 최상위 활용. 0이면 항상 최상위(탐색 안 함)."""

_MAX_ACTIVE = 5
"""활성 가설 세트 상한(설계 §2.2 "최대 5개 강제"). LLM이 큐레이션 세트를 임의로 무한
늘리지 못하게 confidence 내림차순 상위 N개만 활성으로 둔다(나머지는 archived·이력 보존)."""


class MisconceptionHypothesis(BaseModel):
    """활성 오개념 *가설* 1건 — 후보일 뿐 *확정 라벨 아님*(감쇠·가지치기 대상).

    `confidence`는 이 가설의 *현재* 신뢰로, 증거 없으면 `decay`로 하락하고 새 증거에
    `reinforce`로 상승한다(`MisconceptionMatch.confidence`와 달리 시간 축이 반영된 값).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    misconception_id: str = Field(
        description="가설이 가리키는 `Misconception.id`(매처 결과의 misconception.id와 동일).",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="가설의 *현재* 신뢰(증거 없으면 감쇠·새 증거에 강화). 확정도 아닌 후보 신뢰.",
    )
    turns_since_evidence: int = Field(
        ge=0,
        description="마지막 증거(매치) 이후 경과 턴. 0이면 이번 턴에 증거가 갱신됨.",
    )
    evidence_count: int = Field(
        ge=1,
        description="이 가설을 지지한 누적 증거 수(디버그·UI). 신규 가설은 1에서 시작.",
    )


def decay(confidence: float, turns_elapsed: int, *, half_life: int = _HALF_LIFE_TURNS) -> float:
    """지수 감쇠 — 증거 없이 흐른 턴만큼 가설 신뢰를 반감기 곡선으로 낮춘다(순수).

    `confidence * 0.5 ** (turns_elapsed / half_life)`. `turns_elapsed=0`이면 불변(곱 1.0),
    양수면 단조 감소. 결과는 [0,1]로 클램프한다(입력이 이미 [0,1]이면 곱이 1 이하라
    상한은 보장되나 방어적으로 클램프).

    오개념은 영속 라벨이 아니라 *후보*이므로, 증거가 끊긴 가설은 점진 하락시켜 stale
    가설을 가지치기 대상으로 만든다(낙인 방지).
    """
    decayed: float = confidence * 0.5 ** (turns_elapsed / half_life)
    return max(0.0, min(1.0, decayed))


def reinforce(confidence: float, evidence_confidence: float) -> float:
    """새 증거로 가설 신뢰를 1 쪽으로 끌어올림 — 단조 증가(순수).

    `confidence + (1 - confidence) * evidence_confidence`. 남은 여유(1-confidence)의
    `evidence_confidence` 비율만큼 1에 가까워진다. `evidence_confidence=0`이면 불변,
    1이면 1로 포화. 강화는 *단조 증가*(절대 깎지 않음)이고 결과는 [0,1] 클램프.
    """
    reinforced = confidence + (1.0 - confidence) * evidence_confidence
    return max(0.0, min(1.0, reinforced))


def update_hypotheses(
    current: Sequence[MisconceptionHypothesis],
    matches: Sequence[MisconceptionMatch],
    *,
    turns_elapsed: int = 1,
) -> list[MisconceptionHypothesis]:
    """가설 세트를 1턴 갱신 — 감쇠 → 증거 강화/신규 → 가지치기 → 정렬(순수·결정론).

    절차(입력 비변형 — frozen 가설·항상 새 리스트):
      1. 기존 가설 전부 `decay`(turns_elapsed) 적용·`turns_since_evidence += turns_elapsed`.
      2. 각 `match`에 대해 동일 `misconception.id` 가설이 있으면 `reinforce`
         (evidence_confidence=match.confidence)·`turns_since_evidence=0`·`evidence_count+1`;
         없으면 신규 가설 추가(confidence=match.confidence·turns_since_evidence=0·
         evidence_count=1).
      3. `confidence < _PRUNE_THRESHOLD` 가설 가지치기(stale 정리·낙인 방지).
      4. `confidence` *내림차순* 정렬해 반환(동률은 입력/누적 순서 안정 — sort는 안정).

    매치는 *증거*일 뿐 진단 알고리즘이 아니다(`MisconceptionMatch` 재사용·재구현 0).
    """
    # 1. 기존 가설 감쇠 + 증거 미갱신 턴 가산(딕셔너리로 id→가설 인덱싱·증거 단계에서 갱신).
    decayed: dict[str, MisconceptionHypothesis] = {}
    for hyp in current:
        decayed[hyp.misconception_id] = hyp.model_copy(
            update={
                "confidence": decay(hyp.confidence, turns_elapsed),
                "turns_since_evidence": hyp.turns_since_evidence + turns_elapsed,
            }
        )

    # 2. 매치(증거)로 강화 또는 신규 가설 추가.
    for match in matches:
        mid = match.misconception.id
        existing = decayed.get(mid)
        if existing is not None:
            decayed[mid] = existing.model_copy(
                update={
                    "confidence": reinforce(existing.confidence, match.confidence),
                    "turns_since_evidence": 0,
                    "evidence_count": existing.evidence_count + 1,
                }
            )
        else:
            decayed[mid] = MisconceptionHypothesis(
                misconception_id=mid,
                confidence=match.confidence,
                turns_since_evidence=0,
                evidence_count=1,
            )

    # 3. 가지치기(임계 미만 제거) → 4. confidence 내림차순 정렬(안정 정렬).
    pruned = [h for h in decayed.values() if h.confidence >= _PRUNE_THRESHOLD]
    pruned.sort(key=lambda h: h.confidence, reverse=True)
    return pruned


class DeactivationReason(str, Enum):
    """가설이 활성 세트에서 빠진 *사유* — MISC-20 (b) 해소율 정직화의 분자 판정 축.

    종전에는 감쇠·반박·해소·캡절단이 전부 같은 `is_active=false`로 수렴해, ⑩ 오개념 해소율이
    "학생이 실제로 넘어선 것"과 "증거 부족으로 조용히 시든 것"을 구분하지 못했다(R2 §2 G4 ·
    `wh1_evaluation._misconception_resolution_from_counts`가 스스로 자백한 한계). 사유를 분리해
    **RESOLVED만 분자로 세는 것**이 재승격의 전제다.

    `RESOLVED`(해소)의 정의는 좁게 고정한다 — *반박으로 탈락했고* 그 반박 증거 중에 **정정
    형태를 직접 보인 강한 반박**(`coach._log_refutation_evidence`의 `_REFUTE_STRONG_WEIGHT`
    경로 = `correct_form_present` True)이 실재하는 경우만이다. 막연한 clean 풀이의 약한 반박
    (0.5)은 `REFUTED`에 머문다 — "안 틀렸다"는 "넘어섰다"가 아니다(과대해석 금지).
    """

    RESOLVED = "resolved"
    """해소 — 정정 형태를 직접 보인 강한 반박 증거로 탈락(학생이 실제로 넘어섬). 유일한 분자."""

    REFUTED = "refuted"
    """반박 — 증거 순지지도가 음수로 돌아 탈락(강한 반박 증거는 없음)."""

    DECAYED = "decayed"
    """감쇠 — 증거 미갱신으로 confidence가 임계 미만이 되어 가지치기(stale 정리)."""

    CAPPED = "capped"
    """캡 절단 — 상위 N개 제한에 밀려 탈락(가설 자체가 부정된 것이 아니다)."""


def curate_with_reasons(
    current: Sequence[MisconceptionHypothesis],
    matches: Sequence[MisconceptionMatch],
    *,
    turns_elapsed: int = 1,
    refuted: frozenset[str] = frozenset(),
    resolved: frozenset[str] = frozenset(),
    max_active: int = _MAX_ACTIVE,
) -> tuple[list[MisconceptionHypothesis], dict[str, DeactivationReason]]:
    """`curate`와 동일한 생존 세트 + **탈락 사유 맵**을 함께 반환(순수·결정론·MISC-20).

    `curate`는 생존 세트만 돌려줘 "왜 빠졌는지"가 호출자에 도달하지 못했다 — 저장소가 모든
    탈락을 같은 `is_active=false`로 눌러 쓴 근본 원인이다. 이 함수는 같은 파이프라인을 단계별로
    관측해 사유를 붙인다(로직 재구현 0 — `update_hypotheses`·슬라이스 규칙 그대로).

    사유 우선순위(단계 순서 그대로): **감쇠 → 반박/해소 → 캡절단**. 감쇠로 이미 사라진 가설은
    반박 집합에 있어도 `DECAYED`다(반박 판정이 닿기 전에 임계에서 탈락했다 — 시간 순서가 곧
    우선순위이며 별도 규칙을 발명하지 않는다).

    `resolved`는 `refuted`의 *부분집합으로 취급*된다 — 반박으로 탈락하지 않은 가설은 강한 증거가
    있어도 활성이므로 사유 자체가 없다. 두 집합의 판정은 증거 그래프(DB) 몫이라 이 순수 함수는
    id 집합으로 주입받는다(`curate`의 `refuted` 규약 승계).

    사유 맵의 키는 **`current`에 있던 가설만**이다 — 이번 턴 신규 매치는 영속 행이 없어 "탈락"
    개념이 성립하지 않는다. 생존 세트는 `curate`와 항상 동일하다(동치 테스트로 동결).
    """
    survivors_after_prune = update_hypotheses(current, matches, turns_elapsed=turns_elapsed)
    surviving_ids = {h.misconception_id for h in survivors_after_prune}
    existing_ids = {h.misconception_id for h in current}

    reasons: dict[str, DeactivationReason] = {}
    # 1단계 — 감쇠·임계 가지치기로 사라진 기존 가설.
    for mid in existing_ids - surviving_ids:
        reasons[mid] = DeactivationReason.DECAYED

    # 2단계 — 반박 제거(강한 반박 증거가 있으면 해소).
    after_refute = [h for h in survivors_after_prune if h.misconception_id not in refuted]
    for h in survivors_after_prune:
        mid = h.misconception_id
        if mid not in refuted or mid not in existing_ids:
            continue
        reasons[mid] = (
            DeactivationReason.RESOLVED if mid in resolved else DeactivationReason.REFUTED
        )

    # 3단계 — 최대 N 캡 절단.
    kept = after_refute[:max_active]
    for h in after_refute[max_active:]:
        if h.misconception_id in existing_ids:
            reasons[h.misconception_id] = DeactivationReason.CAPPED
    return kept, reasons


def curate(
    current: Sequence[MisconceptionHypothesis],
    matches: Sequence[MisconceptionMatch],
    *,
    turns_elapsed: int = 1,
    refuted: frozenset[str] = frozenset(),
    max_active: int = _MAX_ACTIVE,
) -> list[MisconceptionHypothesis]:
    """활성 가설 세트를 1턴 *큐레이션* — 갱신 → 반박 제거 → 최대 N 캡(순수·결정론).

    `update_hypotheses`(감쇠→증거 강화/신규→임계 가지치기→내림차순 정렬) 위에 설계 §2.2의
    두 큐레이션 규칙을 더한다(재구현 0·조합):
      1. **반박 제거** — `refuted`(증거 *순지지도가 음수*인 오개념 id 집합)에 든 가설을 세트에서
         archived(제외)한다(§5.1 "반박된 가설 archived"·§2.2 규칙3 반박 증거 우선). 반박 판정
         *자체*는 증거 그래프(`evidence_store.net_support`) 몫이라 본 함수는 *id 집합으로 주입*
         받는다 — DB·증거를 모르는 순수 함수로 유지(확증편향 방지가 LLM 추론이 아닌 증거 기반).
      2. **최대 N 캡** — confidence 내림차순 상위 `max_active`개만 활성(§2.2 "최대 5개 강제").
         `update_hypotheses`가 이미 내림차순 정렬하므로 `[:max_active]` 슬라이스로 충분하다.

    `refuted=∅`·`max_active≥세트크기`이면 `update_hypotheses`와 동치다(순수 상위 호환). 입력은
    변형하지 않고 항상 새 리스트를 반환한다(`update_hypotheses` 불변 승계).

    **MISC-20 이후 구현**: 본 함수는 `curate_with_reasons`의 생존 세트를 그대로 돌려주는 얇은
    래퍼다 — 파이프라인 구현은 **하나**뿐이다. 사본을 두면 한쪽만 고쳐질 때 두 경로가 같은
    입력에 다른 판정을 내며, 그것이 `test_coach_wh1_convergence_governance.py`가 동결하는 바로
    그 위험이다. 사유가 필요 없는 호출자(하네스 in-memory 루프)는 계속 이 이름을 쓴다.
    """
    survivors, _reasons = curate_with_reasons(
        current, matches, turns_elapsed=turns_elapsed, refuted=refuted, max_active=max_active
    )
    return survivors


def select_focus(
    hypotheses: Sequence[MisconceptionHypothesis],
    *,
    epsilon: float = _DEFAULT_EPSILON,
    rng: random.Random | None = None,
) -> MisconceptionHypothesis | None:
    """ε-규칙으로 개입 대상 가설 1개 선택 — 활용(최상위) vs 탐색(차순위)(순수·결정론).

    `hypotheses`는 `update_hypotheses`가 내림차순 정렬한 세트를 가정한다(재정렬 안 함).
      - 빈 입력 → None.
      - `rng`가 None이면 *탐색하지 않는다*(항상 최상위 — 결정론·전역 random 금지).
      - `rng.random() < epsilon`이고 차순위가 *있으면* → **탐색**: `hypotheses[1:]`에서
        무작위 1개. 차순위가 없으면(원소 1개) 최상위로 폴백.
      - 그 외 → **활용**: 최상위(`hypotheses[0]`).

    ε-규칙 근거: 항상 1위만 보면 초기 오진단이 *고착*(이후 증거를 1위 가설로만 해석)된다.
    가끔 차순위를 탐색해 가설 세트를 갱신·교정한다. 이는 보상 신호를 악용하는 R-S
    보상해킹이 아니라, 진단 다양성 유지용 단순 탐색이다. 결정론 테스트는 시드 rng 주입.
    """
    if not hypotheses:
        return None
    if rng is not None and len(hypotheses) > 1 and rng.random() < epsilon:
        # 탐색 — 최상위를 제외한 차순위 중 무작위 1개.
        return rng.choice(list(hypotheses[1:]))
    # 활용 — 최상위(이미 confidence 내림차순 정렬 가정).
    return hypotheses[0]


__all__ = [
    "DeactivationReason",
    "MisconceptionHypothesis",
    "curate",
    "curate_with_reasons",
    "decay",
    "reinforce",
    "select_focus",
    "update_hypotheses",
]
