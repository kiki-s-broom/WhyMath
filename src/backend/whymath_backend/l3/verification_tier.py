"""검증 등급 — `verify` 계약의 최소 확장(S4-55).

S4-55에서 tier를 "증명된 축의 집합"으로 개편하되, 기존 `MACHINE_EXHAUSTIVE`와
`MACHINE_SAMPLED`는 legacy alias로 유지해 마이그레이션 없이 기존 코퍼스를 읽는다.
읽을 때의 매핑은 `MACHINE_EXHAUSTIVE`→`FINITE_EXHAUSTIVE`, `MACHINE_SAMPLED`→
`NUMERIC_SAMPLING`이다(레거시 문자열 1개는 멤버 1개로만 해석된다). `STATISTICAL_ESTIMATE`는
레거시 값의 alias 대상이 아니라 신규 생산자가 직접 각인하는 등급이다.

등급 서열:
  ① 기계 증명/결정론 — `FINITE_EXHAUSTIVE`, `SYMBOLIC_PROOF`, `DETERMINISTIC_DATA`
  ② 기계 측정 — `NUMERIC_SAMPLING`, `STATISTICAL_ESTIMATE`
  ③ 잔여 검증 — `RESIDUE_REVIEWED`, `HUMAN_REVIEWED`

어떤 등급도 단독으로 학생 노출 자격을 주지 않는다. 노출 판정은 두 독립 축이며 합치지 않는다
— `is_exposable`(L6, 저작권 출처만 본다)과 `is_review_cleared`(L6, 검수 축).

7계층: L3 지역. 순수 enum·매핑(의존 0).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

__all__ = [
    "VERIFICATION_TIER_KEY",
    "UnknownVerificationTierError",
    "VerificationTier",
    "read_verification_tier",
    "stamp_verification_tier",
]

VERIFICATION_TIER_KEY = "verification_tier"
"""코퍼스 레코드의 `verify` 딕셔너리 안 키 이름(신규 필드·단 하나)."""


class VerificationTier(str, Enum):
    """수치 축이 *어떻게* 검산됐는가. 서술 축(발문↔형식모델 정합)은 어느 값에서도 미검증."""

    # 레거시 alias — 기존 코퍼스 하위호환. 의미는 v1 그대로 유지.
    MACHINE_EXHAUSTIVE = "machine_exhaustive"
    """v1 이름 — "유한 전수 열거"에 한정된 legacy alias.

    SymPy 증명/데이터 전수는 별도 등급(`SYMBOLIC_PROOF`/`DETERMINISTIC_DATA`)을 부여받으므로
    이 레거시 값에서 추론하지 않는다(Codex P2 피드백).
    """

    MACHINE_SAMPLED = "machine_sampled"
    """v1 이름 — "난수 표본 검산·통계 추정"에 한정된 legacy alias."""

    # 신규 — 기계 증명/결정론
    FINITE_EXHAUSTIVE = "finite_exhaustive"
    """유한 집합 전수 열거(확률·기하 이산·통계 자료)."""

    SYMBOLIC_PROOF = "symbolic_proof"
    """SymPy 동치·형식 증명."""

    DETERMINISTIC_DATA = "deterministic_data"
    """주어진 유한 데이터 전수 검증."""

    # 신규 — 기계 측정
    NUMERIC_SAMPLING = "numeric_sampling"
    """Tier1 난수 샘플링."""

    STATISTICAL_ESTIMATE = "statistical_estimate"
    """통계적 추정(신뢰구간 등)."""

    # 신규 — 잔여 검증
    RESIDUE_REVIEWED = "residue_reviewed"
    """LLM 교차검증 + Wilson 게이트 통과 로트."""

    HUMAN_REVIEWED = "human_reviewed"
    """인간 폴백 완료."""


# 레거시 값 → 신규값 alias 해석. 값이 직접 들어오면 그대로 쓴다.
_TIER_ALIASES: dict[str, VerificationTier] = {
    VerificationTier.MACHINE_EXHAUSTIVE.value: VerificationTier.FINITE_EXHAUSTIVE,
    VerificationTier.MACHINE_SAMPLED.value: VerificationTier.NUMERIC_SAMPLING,
}


class UnknownVerificationTierError(ValueError):
    """미지 등급 값 — 조용히 무시하지 않고 오류로 드러낸다(침묵 실패 금지)."""


def _resolve_tier(raw: str) -> VerificationTier:
    """raw 문자열을 alias 해석 후 VerificationTier로 변환."""
    if raw in _TIER_ALIASES:
        return _TIER_ALIASES[raw]
    try:
        return VerificationTier(raw)
    except ValueError as exc:
        raise UnknownVerificationTierError(f"미지 검증 등급: {raw!r}") from exc


def read_verification_tier(verify: Mapping[str, object]) -> VerificationTier | None:
    """코퍼스 레코드의 `verify`에서 등급을 읽는다. 키 부재는 None(등급 미명시).

    값은 문자열이든 `VerificationTier` 멤버든 같은 alias 규칙으로 해석한다(레거시
    `MACHINE_EXHAUSTIVE`→`FINITE_EXHAUSTIVE`, `MACHINE_SAMPLED`→`NUMERIC_SAMPLING`).

    값이 있으나 미지 문자열이면 `UnknownVerificationTierError` — 신설 등급이 조용히
    "미명시"로 강등돼 게이트를 통과하는 경로를 막는다.
    """
    raw = verify.get(VERIFICATION_TIER_KEY)
    if raw is None:
        return None
    if isinstance(raw, VerificationTier):
        # 멤버 입력도 문자열 입력과 같은 alias 규칙을 타도록 값으로 환원해 해석한다(S4-72).
        # 예전에는 raw를 그대로 돌려줘 레거시 멤버만 alias를 건너뛰었다.
        return _resolve_tier(raw.value)
    if not isinstance(raw, str):
        raise UnknownVerificationTierError(f"{VERIFICATION_TIER_KEY}는 문자열이어야 함: {raw!r}")
    return _resolve_tier(raw)


def stamp_verification_tier(record: dict[str, object], tier: VerificationTier) -> dict[str, object]:
    """코퍼스 레코드 JSON의 `verify`에 등급을 찍는다(원본 불변·얕은 사본 반환).

    `verify` 절이 없거나 딕셔너리가 아니면 `ValueError` — 등급만 떠 있는 레코드를 만들지
    않는다(등급은 검산 재료와 한 몸이어야 의미가 있다).
    """
    verify = record.get("verify")
    if not isinstance(verify, dict):
        raise ValueError("verify 절이 없는 레코드에는 검증 등급을 찍을 수 없음")
    stamped = dict(record)
    stamped["verify"] = {**verify, VERIFICATION_TIER_KEY: tier.value}
    return stamped
