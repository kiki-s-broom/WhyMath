"""데이터 등급 → 클라우드(국외) 반출 게이트 — L3 라우팅의 *법적* 축 (EOS-59).

왜 이 게이트를 `guard_cloud`에 합치지 않는가
--------------------------------------------
`router.guard_cloud`(03a §D.4)는 **비즈니스 규칙**이다 — 구독 등급·잔여 예산. 프로모션·요금제
개편·결제 배선으로 언제든 완화될 수 있고, 그 완화 결정은 우리 안에서 끝난다.
이 모듈은 **법적 규칙**이다 — 데이터 제공자와의 이용 조건. 완화하려면 권리자와의 *별도합의*가
필요하다(AIHub 4조건 ②). 두 축을 한 함수에 합치면 "무료 사용자에게도 클라우드를 열자"는
비즈니스 결정이 법적 게이트까지 조용히 여는 경로가 생긴다 — 그 순간 라이선스 위반이 코드
리뷰에서 *구독 정책 변경*처럼 보이게 된다.

저장소에 정확히 같은 논거의 선례가 있다: `l6/_shared.py`의 `is_exposable`(저작권 축)과
`is_review_cleared`(검수 축)는 절대 합치지 않고 **호출부에서 각각 독립된 `if`로** 확인한다.
데이터 등급 게이트도 같은 규율을 따른다 — `Router`가 `guard_cloud`(비즈니스)와
`guard_data_export`(법적)를 각각 독립적으로 통과시킨다.

무엇을 "국외 반출"로 보는가
--------------------------
`CostTier.CLOUD_MID`/`CLOUD_HIGH`가 가리키는 프로바이더(Anthropic 등)는 **국외 법인**이다.
따라서 클라우드 티어로 프롬프트를 보내는 것은 그 프롬프트에 실린 자료의 *국외 이전*이다.
`docs/data/licensing_safety.md` §133 AIHub 4조건 ②("국외반출·국외법인 별도합의")에 따라,
AIHub 유래 자료를 별도합의 없이 클라우드로 보내면 **라이선스 위반**이다. 이는 비용·품질
최적화 문제가 아니라 CLAUDE.md 의사결정 우선순위 **#2(법적·윤리적 준수)** 사안이며,
**#6(비용·효율)을 이긴다** — 이 게이트는 비용 최적화보다 앞선다.

권리 판정의 정본은 여기가 아니다 (단일 진실 원천)
------------------------------------------------
"AIHub 자료는 반출 불가"라는 사실을 이 모듈이 새로 정하지 않는다 — **이미 선언돼 있다**:
`l1/rights/permission_map.py`의 `_AIHUB_OPEN`이 `export=False  # 국외반출 금지`를 박아 뒀다.
이 모듈이 하는 일은 그 *선언된 권리 사실을 라우팅 결정에 배선*하는 것뿐이다. 그래서 등급
어휘를 새로 발명하지 않고 기존 `LicenseType` × `PermissionAction.EXPORT`를 **그대로** 쓴다 —
새 등급 스케일을 만들면 그 순간 권리 기준이 두 벌이 되고(기준 이원화), 한쪽만 고쳐지는 날이
반드시 온다. 라이선스가 곧 등급이고, 등급의 의미는 권리 모델이 정의한다.

단방향성 (승급 불가)
-------------------
이 게이트는 **오직 강등만** 한다 — 클라우드를 `LOCAL`로 내릴 수는 있어도 어떤 경우에도
티어를 *올릴* 수 없다. 법적 게이트가 성능·품질 판단에 개입하면 그건 더 이상 게이트가 아니라
라우팅 정책이 된다. 이 성질은 `guard_data_export`의 반환값이 `{desired, LOCAL}` 두 값만
가진다는 것으로 코드에 못박혀 있고, 테스트(전 티어 × 전 라이선스 격자)와
`RoutingDecision`의 불변식 5(`data_export_blocked ⟹ cost_tier == LOCAL`)가 상시 봉인한다.

fail-closed 기본값
------------------
`permission_map`의 `export`는 3값이다 — `True`(허용)/`False`(금지)/`None`(미확인).
**`None`은 허용이 아니다** — 확인되지 않은 반출은 차단한다(정책 엔진의 fail-closed 관례
동형: `policy_engine._license_decision`이 `None`을 `REVIEW_REQUIRED`로 올린다). 그래서
`LicenseType.UNKNOWN`(= `RoutingRequest.data_licenses`의 기본값)은 클라우드를 막는다.

그 보수 기본값이 *일상 동작*이 되면 클라우드가 사실상 꺼진다. 그래서 이 게이트는
**소스 스캔 게이트**(`scripts/ops/check_routing_data_grade.py`, CI `backend` 잡)와 한 쌍이다 —
프로덕션 호출부는 등급을 *명시*해야 하고, 기본값은 그 명시를 잊었을 때만 작동하는
**사고 방지용 backstop**으로 남는다. 그 스캐너는 *입력*만 보므로, `RoutingDecision`을 손으로
조립해 `Router.route`(유일한 집행 지점)를 건너뛰는 우회는 **결정 스캔 게이트**
(`scripts/ops/check_routing_decision_bypass.py`, EOS-77)가 따로 막는다 — 클라우드 티어 리터럴
직접 생성 금지·비리터럴 티어는 `data_export_reason` 승계 필수·유예는 만료·unmatched 강제.

7계층: L3 → L1(권리 모델)·`schema`만 의존한다(하위 방향). 순수 함수·I/O 없음.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from whymath_backend.l1.rights.permission_map import license_to_permission_set
from whymath_backend.l3.models import CostTier, RoutingRequest
from whymath_backend.schema.enums import LicenseType, PermissionAction

__all__ = [
    "EXPORT_ALLOWED",
    "EXPORT_PROHIBITED",
    "EXPORT_UNVERIFIED",
    "EXPORT_REASONS",
    "OFFSHORE_TIERS",
    "ExportJudgment",
    "export_judgment",
    "export_judgment_for",
    "guard_data_export",
    "normalize_licenses",
]


# ──────────────────────────────────────────────────────────────────────────
# 판정 사유 코드 — `policy_engine`의 `reason_code` 관례(대문자 스네이크) 답습.
# 값 자체가 Langfuse 필드·리포트 집계 키로 나가므로 문자열을 고정한다.
# ──────────────────────────────────────────────────────────────────────────
EXPORT_ALLOWED: Final[str] = "EXPORT_ALLOWED"
"""전 자료가 `export=True` — 국외 반출(클라우드) 허용."""

EXPORT_PROHIBITED: Final[str] = "EXPORT_PROHIBITED"
"""자료 중 하나 이상이 `export=False` — 명시적 반출 금지(AIHub·사용자 자작·RESTRICTED)."""

EXPORT_UNVERIFIED: Final[str] = "EXPORT_UNVERIFIED"
"""반출 권한 미확인(`export=None`) — fail-closed로 금지와 동일하게 차단한다."""

EXPORT_REASONS: Final[tuple[str, ...]] = (
    EXPORT_ALLOWED,
    EXPORT_PROHIBITED,
    EXPORT_UNVERIFIED,
)
"""판정 사유 3종 — 리포트가 버킷 키를 모두 보장하기 위해 쓴다(미관측=0과 미상 구분)."""

OFFSHORE_TIERS: Final[frozenset[CostTier]] = frozenset({CostTier.CLOUD_MID, CostTier.CLOUD_HIGH})
"""국외 법인 프로바이더로 나가는 티어 — 이 티어로의 라우팅이 곧 *국외 이전*이다.

`CostTier.LOCAL`(Phaiakes9)은 국내 온프레미스라 반출이 아니다. 새 클라우드 티어를 추가하면
여기에도 넣어야 한다 — 빠뜨리면 그 티어만 게이트를 우회한다(그래서 상수로 둔다).
"""


# ──────────────────────────────────────────────────────────────────────────
# 판정 결과
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ExportJudgment:
    """자료 묶음 1건에 대한 국외 반출 가부 판정 — 티어와 무관한 *순수 법적* 판단.

    티어를 모르는 채로도 성립한다(라우팅에서 분리) — 그래야 이 판정을 리포트·감사·다른
    반출 경로(백업·분석 export 등)에서 재사용할 수 있고, 라우팅 규칙이 바뀌어도 법적
    판정이 따라 흔들리지 않는다.
    """

    permitted: bool | None
    """3값 그대로 보존 — True(허용)/False(금지)/None(미확인). `None`을 `False`로 뭉개지
    않는다: 차단 *동작*은 같아도 "금지됐다"와 "확인 못 했다"는 다른 사실이고, 후자는
    권리 확인으로 풀리는 문제다(모르면 모른다고 — CLAUDE.md)."""

    reason: str
    """`EXPORT_ALLOWED` / `EXPORT_PROHIBITED` / `EXPORT_UNVERIFIED` 중 하나."""

    blocking_licenses: tuple[LicenseType, ...]
    """차단을 유발한 라이선스들(허용이면 빈 튜플). 어느 자료 때문에 막혔는지 추적용."""

    @property
    def blocks_offshore(self) -> bool:
        """국외(클라우드) 반출을 막아야 하는가 — `permitted is True`가 아니면 전부 차단."""
        return self.permitted is not True


# ──────────────────────────────────────────────────────────────────────────
# 정규화 — `use_enum_values=True` 대응
# ──────────────────────────────────────────────────────────────────────────
def normalize_licenses(values: Iterable[object]) -> tuple[LicenseType, ...]:
    """enum/문자열 섞인 라이선스 목록을 `LicenseType` 튜플로 정규화한다.

    `RoutingRequest`는 `use_enum_values=True`라 필드에 담긴 값이 *문자열*일 수 있다
    (`router._as_cost_tier` 등이 같은 이유로 존재한다). 테스트·직접 호출은 enum을 넘기므로
    양쪽을 다 받는다.

    미지의 문자열은 **조용히 UNKNOWN으로 반올림하지 않고 `ValueError`로 던진다** — 여기서
    삼키면 오타 하나가 "미확인이라 어차피 차단"이라는 *우연한 안전*으로 위장되고, 반대로
    라이선스 enum이 확장됐을 때 조용히 잘못 분류될 수 있다(침묵 실패 금지).
    """
    normalized: list[LicenseType] = []
    for value in values:
        if isinstance(value, LicenseType):
            normalized.append(value)
            continue
        if isinstance(value, str):
            normalized.append(LicenseType(value))  # 미지 값이면 ValueError(의도적 전파)
            continue
        raise TypeError(
            f"라이선스 값은 LicenseType 또는 문자열이어야 한다(받은 값 {type(value)!r})"
        )
    return tuple(normalized)


# ──────────────────────────────────────────────────────────────────────────
# 법적 판정 (보수적 병합)
# ──────────────────────────────────────────────────────────────────────────
def export_judgment(licenses: Iterable[object]) -> ExportJudgment:
    """자료 묶음의 국외 반출 가부 — 권리 모델(L1)에 위임하고 *보수적으로 병합*한다.

    병합 규칙(`policy_engine.DecisionPriority.worst` 동형 — 가장 제한적인 판정이 이긴다):
      1. 하나라도 `export=False`  → `EXPORT_PROHIBITED`(금지가 최우선)
      2. 그 외에 하나라도 `None`  → `EXPORT_UNVERIFIED`(미확인은 fail-closed로 차단)
      3. 전부 `True`              → `EXPORT_ALLOWED`
    빈 목록은 "실린 자료가 없다"가 아니라 **"무엇이 실렸는지 모른다"**로 읽어 `UNVERIFIED`로
    떨어뜨린다(`RoutingRequest`는 애초에 빈 목록을 스키마에서 거부한다 — 이중 방어).

    각 라이선스의 반출 권한은 이 함수가 판단하지 않는다 —
    `l1.rights.permission_map.license_to_permission_set(...).allows(EXPORT)`가 정본이다.
    AIHub가 왜 금지인지(`_AIHUB_OPEN.export=False  # 국외반출 금지`)는 그쪽에 적혀 있고,
    조건을 바꾸려면 그쪽을 고친다 — 이 함수는 그 사실을 *읽기만* 한다.
    """
    resolved = normalize_licenses(licenses)
    if not resolved:
        return ExportJudgment(permitted=None, reason=EXPORT_UNVERIFIED, blocking_licenses=())

    prohibited: list[LicenseType] = []
    unverified: list[LicenseType] = []
    for license_type in resolved:
        allowed = license_to_permission_set(license_type).allows(PermissionAction.EXPORT)
        if allowed is False:
            prohibited.append(license_type)
        elif allowed is None:
            unverified.append(license_type)

    if prohibited:
        return ExportJudgment(
            permitted=False,
            reason=EXPORT_PROHIBITED,
            blocking_licenses=tuple(prohibited),
        )
    if unverified:
        return ExportJudgment(
            permitted=None,
            reason=EXPORT_UNVERIFIED,
            blocking_licenses=tuple(unverified),
        )
    return ExportJudgment(permitted=True, reason=EXPORT_ALLOWED, blocking_licenses=())


def export_judgment_for(req: RoutingRequest) -> ExportJudgment:
    """`RoutingRequest`의 선언 등급에 대한 반출 판정 — 호출부 편의 래퍼.

    라우터·관측·프로브가 같은 필드(`data_licenses`)를 각자 꺼내 읽지 않게 한 자리로 모은다.
    """
    return export_judgment(req.data_licenses)


# ──────────────────────────────────────────────────────────────────────────
# 게이트 (단방향 강등 전용)
# ──────────────────────────────────────────────────────────────────────────
def guard_data_export(desired: CostTier, licenses: Iterable[object]) -> CostTier:
    """희망 티어에 데이터 등급(법적) 게이트를 적용한다 — **강등만** 한다.

    `guard_cloud`(구독·예산)와 시그니처 모양을 맞춰 "가드가 둘"임을 읽기 쉽게 했지만,
    **합치지 않는다**(모듈 docstring 참조). 호출부는 두 가드를 각각 독립된 단계로 통과시킨다.

    규칙:
      - 희망이 국외 티어가 아니면(= `LOCAL`) 반출 자체가 없다 → 그대로 둔다.
        (이때 자료가 반출 금지여도 "게이트가 발동했다"고 하지 않는다 — 막을 것이 없었다.)
      - 희망이 국외 티어인데 반출이 허용되지 않으면(`False` 또는 `None`) → `LOCAL`로 강등.
      - 반출 허용이면 희망 티어 그대로.

    반환값은 항상 `desired` 또는 `CostTier.LOCAL` 둘 중 하나다 — **어떤 입력으로도 티어가
    올라가지 않는다**(단방향성). 이 성질은 반환 경로가 이 두 값밖에 없다는 사실로 코드에
    못박혀 있고, 전 티어 × 전 라이선스 격자 테스트가 상시 재확인한다.
    """
    # 티어 정규화 — `RoutingDecision.cost_tier`는 `use_enum_values=True`라 문자열일 수 있다.
    # `CostTier(str, Enum)`이라 문자열도 `OFFSHORE_TIERS` 멤버십에 걸리지만, *미지의* 문자열
    # (오타·신규 티어)은 조용히 "국외 아님"으로 통과해 게이트를 우회한다. 여기서 변환하면
    # 그 경우가 침묵 통과가 아니라 `ValueError`가 된다(모르면 막는다 — 법적 축).
    tier = desired if isinstance(desired, CostTier) else CostTier(desired)
    if tier not in OFFSHORE_TIERS:
        return tier  # 국내(로컬) — 판정할 반출이 없다
    if export_judgment(licenses).blocks_offshore:
        return CostTier.LOCAL  # 반출 불가/미확인 → 국내 강등(법적 우선순위 #2)
    return tier
