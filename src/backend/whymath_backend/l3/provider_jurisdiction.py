"""프로바이더 관할(jurisdiction) 축 — "어느 나라 법인이 이 요청을 받는가" (ARCH-49).

왜 `CostTier`에 티어를 하나 더 만들지 않는가
-------------------------------------------
DeepSeek 공식 API는 중국 본토 서버 전용이고 데이터 레지던시 선택지가 없다(2026-09 실측).
그래서 "CN 전용 티어를 하나 더 만들자"가 제일 먼저 떠오르지만, 그러면 `OFFSHORE_TIERS`·
`RoutingDecision`의 세 축 불변식·`LOCAL_MODEL_MATRIX`·라우터 결정표를 전부 손봐야 한다 —
구축 플레이북 7대 붕괴 연쇄 ②(관계 폭발)의 축 버전이다.

대신 **축을 분리**한다(8대 구조 원칙 ② Layer Separation):

- `CostTier`는 계속 **"얼마나 비싼가·어디서 도는가"**만 말한다(local / cloud_mid / cloud_high).
- `Jurisdiction`은 **"어느 나라 법인인가"**를 말하며, 티어가 아니라 **프로바이더**에 붙는다.

같은 `CLOUD_MID` 티어라도 Anthropic(US)으로 갈 수도, DeepSeek(CN)으로 갈 수도 있다 —
비용 등급은 같고 관할이 다르다. 두 사실을 한 enum에 밀어 넣으면 둘 중 하나가 반드시
거짓이 된다.

이 모듈은 기존 법적 게이트를 **대체하지 않는다** (겹겹이 좁힌다)
--------------------------------------------------------------
`l3.data_export_policy`(EOS-59)가 1차 게이트다 — 라이선스가 국외 반출을 허용하는가.
이 모듈은 그 **위에 겹치는 2차 좁힘**이며, 절대 넓히지 않는다:

    관할 허용 등급  ⊆  반출 허용 등급(EXPORT_PERMITTED_LICENSES)

그 부분집합 성질은 `allowed_licenses_for`가 **항상 `EXPORT_PERMITTED_LICENSES`와 교집합을
취해** 코드로 못박는다 — 정책 표에 실수로 반출 금지 등급을 적어도 넓혀지지 않는다.
따라서 학생 저작(`USER_GENERATED.export=False`)은 어떤 관할로도 나갈 수 없다: 1차 게이트가
이미 `LOCAL`로 강등하고(`guard_data_export`), 설령 그 게이트를 우회한 결정이 와도 이
모듈의 허용 집합에 `USER_GENERATED`가 들어갈 방법이 없다. 이것이 acceptance ②가 요구한
"기계가 판정하는 불변식"이며, 두 겹 중 어느 한 겹이 깨져도 성립한다.

CN 기본값이 보수적인 이유 (법적 판정과 영업자산 판정은 다른 축)
-------------------------------------------------------------
`INTERNAL_OWNED`(자체 저작 코퍼스)는 **법적으로는** 반출 가능하다(`export=True`). 그런데도
CN 기본 허용에서 뺀다 — 개념 그래프·오개념 카탈로그·교수학 프롬프트는 이 프로젝트의
영업자산이고, "합법적으로 보낼 수 있다"와 "보내도 되는가"는 다른 질문이기 때문이다.
그래서 CN 기본 허용은 `WHYMATH_GENERATED`(합성 프로브)뿐이고, 코퍼스를 태우려면
`settings.deepseek_allow_internal_corpus` opt-in이 필요하다.

**미확정 사실 1건(명시)**: DeepSeek이 *유료* API 입력을 학습에 쓰는지는 확정되지 않았다 —
2차 자료가 서로 반대로 적고("2026-03 개정으로 유료 API는 학습 제외" vs "빼 주지 않는다"),
1차 자료(`cdn.deepseek.com` 약관)는 조사 세션의 egress 프록시가 차단해 확인하지 못했다.
opt-in을 기본 OFF로 두는 이유가 이것이며, 확인되면 그 근거와 함께 기본값을 재평가한다.

`UNKNOWN`은 왜 "빈 집합"인가
---------------------------
OpenRouter 경유는 **공급사 slug**로 관할이 결정된다(`deepinfra`→US). 우리가 국적을 모르는
slug가 오면 그것은 "아마 괜찮다"가 아니라 **모른다**이며, 모르는 관할로는 아무 등급도 보내지
않는다(fail-closed — `data_export_policy`의 `export=None` 취급과 동형). 이 성질이 ARCH-49
acceptance ⑩의 이중 방어 중 **우리 쪽 방어층**이다: OpenRouter의 `data_collection="deny"`
분류가 틀렸더라도, 우리가 국적을 아는 공급사만 허용목록에 있으므로 계약이 유지된다.

7계층: L3 → L1(권리 모델)·`schema`만 의존한다(하위 방향). 순수 함수·I/O 없음.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

from whymath_backend.l1.rights.permission_map import license_to_permission_set
from whymath_backend.l3.data_export_policy import normalize_licenses
from whymath_backend.schema.enums import LicenseType, PermissionAction

__all__ = [
    "EXPORT_PERMITTED_LICENSES",
    "JURISDICTION_ALLOWED",
    "JURISDICTION_GRADE_BLOCKED",
    "JURISDICTION_REASONS",
    "JURISDICTION_UNDECLARED",
    "Jurisdiction",
    "JurisdictionJudgment",
    "allowed_licenses_for",
    "jurisdiction_judgment",
    "narrows_beyond_export_gate",
    "requires_declared_grades",
]


class Jurisdiction(str, Enum):
    """프로바이더를 운영하는 법인의 관할 — 비용 축(`CostTier`)과 직교한다.

    값은 Langfuse 태그·리포트 집계 키로 나가므로 소문자 문자열로 고정한다.
    """

    DOMESTIC = "domestic"
    """국내 온프레미스(Phaiakes9) — 국외 이전 자체가 없다."""

    US = "us"
    """미국 법인 — Anthropic 공식 API, OpenRouter 경유 `deepinfra`·`digitalocean` 등."""

    CN = "cn"
    """중국 법인 — DeepSeek 공식 API(본토 서버 전용·레지던시 선택 불가, 2026-09 실측)."""

    UNKNOWN = "unknown"
    """국적 미확인 — 허용 등급 없음(fail-closed). 모르는 OpenRouter 공급사 slug가 여기 온다."""


# ──────────────────────────────────────────────────────────────────────────
# 판정 사유 코드 — `data_export_policy.EXPORT_*` 관례(대문자 스네이크) 답습.
# ──────────────────────────────────────────────────────────────────────────
JURISDICTION_ALLOWED: Final[str] = "JURISDICTION_ALLOWED"
"""선언된 전 등급이 해당 관할의 허용 집합 안 — 통과."""

JURISDICTION_GRADE_BLOCKED: Final[str] = "JURISDICTION_GRADE_BLOCKED"
"""선언된 등급 중 하나 이상이 그 관할에 허용되지 않음 — 차단."""

JURISDICTION_UNDECLARED: Final[str] = "JURISDICTION_UNDECLARED"
"""등급이 선언되지 않았는데 그 관할은 선언을 요구함 — fail-closed 차단.

"자료가 없다"가 아니라 **"무엇이 실렸는지 모른다"**로 읽는다
(`data_export_policy.export_judgment`가 빈 목록을 `EXPORT_UNVERIFIED`로 떨어뜨리는 것과 동형).
"""

JURISDICTION_REASONS: Final[tuple[str, ...]] = (
    JURISDICTION_ALLOWED,
    JURISDICTION_GRADE_BLOCKED,
    JURISDICTION_UNDECLARED,
)
"""판정 사유 3종 — 리포트가 버킷 키를 모두 보장하기 위해 쓴다(미관측=0과 미상 구분)."""


def _export_permitted() -> frozenset[LicenseType]:
    """반출(`PermissionAction.EXPORT`)이 **명시적으로 허용**된 등급 집합을 권리 모델에서 유도.

    `allows(EXPORT)`가 `True`인 것만 담는다 — `None`(미확인)은 허용이 아니다(fail-closed,
    `data_export_policy` 모듈 docstring). 이 집합을 여기서 손으로 열거하지 않는 이유는
    단일 진실 원천이다: 어느 등급이 반출 가능한지는 `l1/rights/permission_map.py`가 정하고,
    이 모듈은 그것을 *읽기만* 한다. 권리 모델이 바뀌면 이 집합이 따라 바뀐다.
    """
    return frozenset(
        license_type
        for license_type in LicenseType
        if license_to_permission_set(license_type).allows(PermissionAction.EXPORT) is True
    )


EXPORT_PERMITTED_LICENSES: Final[frozenset[LicenseType]] = _export_permitted()
"""국외 반출이 허용된 등급 — 관할 허용 집합의 **상한**(어떤 관할도 이보다 넓을 수 없다)."""


# 관할별 *선언적* 허용 등급 표. 실제 허용 집합은 `allowed_licenses_for`가 여기에
# `EXPORT_PERMITTED_LICENSES`를 교집합해 만든다 — 이 표만 고쳐서는 절대 넓힐 수 없다.
_BASE_POLICY: Final[dict[Jurisdiction, frozenset[LicenseType]]] = {
    # 국내는 반출이 없다 — 상한(교집합)에 걸려 결국 EXPORT_PERMITTED_LICENSES가 되지만,
    # 국내 디스패치는 애초에 이 게이트를 통과하지 않는다(`narrows_beyond_export_gate` False).
    Jurisdiction.DOMESTIC: frozenset(LicenseType),
    # 미국 법인 — 기존 법적 게이트 그대로. 추가 좁힘 없음(= 현행 Anthropic 경로 무변경).
    Jurisdiction.US: frozenset(LicenseType),
    # 중국 법인 — 합성 프로브만. 코퍼스(`INTERNAL_OWNED`)는 opt-in(아래 인자).
    Jurisdiction.CN: frozenset({LicenseType.WHYMATH_GENERATED}),
    # 국적 미확인 — 아무것도 보내지 않는다.
    Jurisdiction.UNKNOWN: frozenset(),
}

# CN opt-in이 추가로 여는 등급 — `deepseek_allow_internal_corpus=True`일 때만.
_CN_OPT_IN_LICENSES: Final[frozenset[LicenseType]] = frozenset({LicenseType.INTERNAL_OWNED})


@dataclass(frozen=True, slots=True)
class JurisdictionJudgment:
    """관할 1건 × 선언 등급 묶음 1건에 대한 송신 가부 판정.

    `data_export_policy.ExportJudgment`와 모양을 맞춰 두 게이트를 나란히 읽을 수 있게 했지만,
    **합치지 않는다** — 하나는 권리자와의 법적 조건이고 하나는 관할·영업자산 판단이라
    완화 근거가 서로 다르다(`data_export_policy` 모듈 docstring의 같은 논거).
    """

    permitted: bool
    """송신 허용 여부. 3값이 아니라 2값인 이유: 이 축에 "미확인"은 없다 — 선언이 없으면
    `JURISDICTION_UNDECLARED`로 **차단**이고, 그것은 사실 판정(모른다)이 아니라 정책
    결정(모르면 안 보낸다)이다. 미확인이라는 *사실*은 1차 게이트가 이미 기록한다."""

    reason: str
    """`JURISDICTION_ALLOWED` / `JURISDICTION_GRADE_BLOCKED` / `JURISDICTION_UNDECLARED`."""

    blocking_licenses: tuple[LicenseType, ...]
    """차단을 유발한 등급들(허용이거나 미선언이면 빈 튜플). 어느 자료 때문에 막혔는지 추적용."""


def allowed_licenses_for(
    jurisdiction: Jurisdiction,
    *,
    allow_internal_corpus: bool = False,
) -> frozenset[LicenseType]:
    """관할이 허용하는 라이선스 등급 집합 — **항상 반출 허용 상한과 교집합**한다.

    `allow_internal_corpus`는 CN 관할에만 영향을 준다(자체 저작 코퍼스 opt-in). 다른 관할의
    집합은 이 인자로 바뀌지 않는다 — opt-in은 "중국 서버에 우리 영업자산을 보낸다"는 결정
    하나를 가리키며, 다른 관할까지 함께 여는 만능 스위치가 아니다.

    교집합이 핵심이다: 표(`_BASE_POLICY`)에 무엇을 적든 반출 금지 등급은 통과하지 못한다.
    그래서 `USER_GENERATED`(학생 저작, `export=False`)는 **어떤 인자 조합으로도** 결과에
    들어오지 않는다 — 그 성질을 뮤테이션 테스트가 상시 재확인한다.
    """
    base = _BASE_POLICY[jurisdiction]
    if allow_internal_corpus and jurisdiction is Jurisdiction.CN:
        base = base | _CN_OPT_IN_LICENSES
    return base & EXPORT_PERMITTED_LICENSES


def narrows_beyond_export_gate(
    jurisdiction: Jurisdiction,
    *,
    allow_internal_corpus: bool = False,
) -> bool:
    """이 관할이 1차 법적 게이트보다 **더 좁은가**(진부분집합).

    `US`·`DOMESTIC`은 추가 좁힘이 없어 False다 — 즉 현행 Anthropic 경로에 대해 이 축은
    아무 판정도 추가하지 않는다(무변경 보장). `CN`·`UNKNOWN`은 True다.
    """
    return allowed_licenses_for(
        jurisdiction, allow_internal_corpus=allow_internal_corpus
    ) < frozenset(EXPORT_PERMITTED_LICENSES)


def requires_declared_grades(
    jurisdiction: Jurisdiction,
    *,
    allow_internal_corpus: bool = False,
) -> bool:
    """등급 *선언*을 요구하는 관할인가 — 추가 좁힘이 있는 관할만 요구한다.

    좁힘이 없는 관할(US)에서 선언을 요구하면 1차 게이트를 이미 통과한 기존 호출부가 전부
    막힌다 — 그것은 이 축이 하려는 일이 아니다(이 모듈은 *겹치는 2차 좁힘*이지 1차 게이트의
    재구현이 아니다). 반대로 좁힘이 있는 관할에서 선언이 없으면 좁힐 근거 자체가 없으므로
    **보내지 않는다**(fail-closed).
    """
    return narrows_beyond_export_gate(jurisdiction, allow_internal_corpus=allow_internal_corpus)


def jurisdiction_judgment(
    jurisdiction: Jurisdiction,
    licenses: Iterable[object],
    *,
    allow_internal_corpus: bool = False,
) -> JurisdictionJudgment:
    """선언 등급 묶음을 그 관할로 보내도 되는가 — 보수적 병합(하나라도 막히면 차단).

    병합 규칙(`export_judgment`와 동형 — 가장 제한적인 판정이 이긴다):
      1. 선언이 비었고 그 관할이 선언을 요구  → `JURISDICTION_UNDECLARED`(차단)
      2. 선언이 비었고 요구하지 않음          → `JURISDICTION_ALLOWED`(1차 게이트에 위임)
      3. 허용 집합 밖 등급이 하나라도 있음     → `JURISDICTION_GRADE_BLOCKED`(차단)
      4. 그 외                                → `JURISDICTION_ALLOWED`

    등급 문자열 정규화는 `data_export_policy.normalize_licenses`에 위임한다(어휘를 새로
    만들지 않는다 — 미지의 문자열은 그쪽에서 `ValueError`로 전파되고 여기서 삼키지 않는다).
    """
    resolved = normalize_licenses(licenses)
    allowed = allowed_licenses_for(jurisdiction, allow_internal_corpus=allow_internal_corpus)
    if not resolved:
        if requires_declared_grades(jurisdiction, allow_internal_corpus=allow_internal_corpus):
            return JurisdictionJudgment(
                permitted=False,
                reason=JURISDICTION_UNDECLARED,
                blocking_licenses=(),
            )
        return JurisdictionJudgment(
            permitted=True,
            reason=JURISDICTION_ALLOWED,
            blocking_licenses=(),
        )
    # 중복 선언은 한 번만 보고한다(순서는 선언 순서 보존 — 로그 가독성).
    blocking: list[LicenseType] = []
    for license_type in resolved:
        if license_type not in allowed and license_type not in blocking:
            blocking.append(license_type)
    if blocking:
        return JurisdictionJudgment(
            permitted=False,
            reason=JURISDICTION_GRADE_BLOCKED,
            blocking_licenses=tuple(blocking),
        )
    return JurisdictionJudgment(
        permitted=True,
        reason=JURISDICTION_ALLOWED,
        blocking_licenses=(),
    )
