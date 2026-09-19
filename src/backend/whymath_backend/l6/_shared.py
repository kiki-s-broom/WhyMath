"""L6 응용 모드 공용 게이팅 헬퍼 — 저작권 노출 게이트·use_enum_values 정규화.

이 모듈은 L6의 *여러 응용 모드*(RT 재수전용·수능 정시·학교진도)가 공통으로 필요로 하는
**저작권 노출 게이트**와 **enum 값 정규화** 로직의 단일 출처(single source of truth)다.
부수효과 없음(I/O·LLM 호출 없음)·결정적(deterministic)·순수 함수.

**Rule of three 추출 완료**: RT 트랙(`l6/retake/gating.py`)과 수능 모드
(`l6/suneung/gating.py`)는 본래 `METADATA_ONLY_SOURCES`·`_source_value`·`_persona_fit` 같은
저작권 게이트·정규화 헬퍼를 *의도적으로 중복*했다(서로의 파일을 건드리지 않아 무회귀를
보장하려는 선택). 학교진도가 *세 번째* L6 모드로 들어오면서, 두 모듈 docstring이 예고했던
"3번째 모드 시 l6 공용 추출"을 실제로 수행해 그 중복을 여기로 통합한다(Rule of three).
**L6 공용(RT·수능·학교진도 공유)** — 세 모드가 이 모듈의 같은 게이트·정규화를 호출한다.

저작권 근거(CLAUDE.md 우선순위 #2 — 법적): 검정 교과서·평가원·EBS *본문*의 복제·영리이용은
저작권법 §32 단서·§136·§140(영리 비친고죄)로 금지된다(저작권 가이드 v2.0, MEMORY
2026-05-28). 이 세 출처 레코드는 본문 미보유(구조 메타데이터 참조 전용)라 학생에게 노출할
문항으로 쓸 수 없다 — 본문을 가진 문항은 `자체생성`(WHYMATH_GENERATED)뿐이다. L6 응용 모드는
학생에게 문항을 *노출*하므로 본문 미보유 출처를 게이트(`is_exposable`)에서 원천 차단한다.

use_enum_values=True 주의: `Problem`은 `ConfigDict(use_enum_values=True)`라 직렬화·구성
경로에 따라 `source_type`·`question_format`·`exam_type` 같은 enum 필드가 *문자열 값*일 수
있고 `persona_fit`의 *키*도 문자열일 수 있다. 따라서 enum 비교 시 항상 enum/문자열 양쪽을
정규화해 비교한다(`schema/problem.py`의 `_enforce_copyright_no_body_for_metadata_sources`
validator 패턴 답습). `normalize_enum_value`가 그 정규화의 공용 진입점이다.

레이어 규칙(CLAUDE.md): L6→L1만 의존한다(`schema.enums`·`schema.problem`). L4/L2/L3를
import하지 않는다 — 이 모듈은 기존 `Problem` 필드의 *존재·값*만 본다. L6은 아무도 import하지
않는 최상위 소비자다(역방향 의존 부재).

설계 메모(2026-09-18 정정 · EOS-19): 이 집합은 한때 여기서 *재정의*됐다 — 사유는
"`schema.problem._METADATA_ONLY_SOURCES`가 private이라 import할 수 없다"였다. 그 사유가
사라졌으므로(그쪽이 공개 이름 `METADATA_ONLY_SOURCES`가 됐다) 재정의를 걷고 **같은 객체를
재노출**한다. 저작권 차단 집합이 두 벌이면 한쪽만 고쳐지는 날 노출 게이트가 갈라지는데,
그것은 법적 축에서 가장 위험한 드리프트다. 기존 import 경로
(`l6.retake.gating.METADATA_ONLY_SOURCES` 등)는 그대로 동작한다.
"""

from __future__ import annotations

from enum import Enum

# `ReviewStatus` 자체는 더 이상 여기서 비교하지 않는다 — 값 판정을
# `is_review_status_cleared`(L1, 단일 권위)에 위임했기 때문이다(CONT-01).
from whymath_backend.schema.enums import Persona, is_review_status_cleared
from whymath_backend.schema.problem import METADATA_ONLY_SOURCES as _SCHEMA_METADATA_ONLY_SOURCES
from whymath_backend.schema.problem import Problem

# ──────────────────────────────────────────────────────────────────────────
# 게이팅 상수
# ──────────────────────────────────────────────────────────────────────────
#: 학생에게 *본문 노출이 불가*한 출처 — 저작권 노출 게이트의 차단 집합(L6 공용).
#: 정의는 `schema.problem`이 소유한다(아래 docstring의 배경 참조) — 여기서는 재노출만 한다.
METADATA_ONLY_SOURCES = _SCHEMA_METADATA_ONLY_SOURCES
"""학생에게 *본문 노출이 불가*한 출처 — 저작권 노출 게이트의 차단 집합(L6 공용).

평가원·EBS·검정교과서는 *본문·문항 미보유*(WhyMath는 구조 메타데이터만 보유). 이 출처의
레코드는 단원·코드·문항번호 같은 *구조 참조 전용*이며 실제 발문·해설·선지를 가지지 않으므로,
**학생에게 노출할 문항으로 쓸 수 없다**. 노출 가능한 본문을 가진 문항은 `자체생성`
(WHYMATH_GENERATED) 레코드뿐이다.

왜 노출 불가인가: 검정 교과서·평가원·EBS 본문의 복제·영리이용은 저작권법 §32 단서·§136·
§140(영리 비친고죄)로 금지된다(저작권 가이드 v2.0, MEMORY 2026-05-28). L6 응용 모드(RT·수능·
학교진도)는 학생에게 문항을 *노출*하므로, 본문 미보유 출처는 `is_exposable` 게이트에서 원천
차단한다.

**Rule of three 추출 완료**: RT 트랙·수능 모드가 각자 재정의하던 같은 집합을 여기로 통합했다.
두 모드는 하위호환을 위해 이 상수를 `from whymath_backend.l6._shared import METADATA_ONLY_SOURCES`
로 *재노출*한다(기존 import 경로 `l6.retake.gating.METADATA_ONLY_SOURCES` 등이 깨지지 않게).
"""


def normalize_enum_value(value: object) -> str | None:
    """enum/문자열/None을 *문자열 값*으로 정규화한다(use_enum_values=True 대응).

    `Problem`은 `use_enum_values=True`라 enum 필드가 직렬화·구성 경로에 따라 `Enum` 멤버일
    수도, 그 문자열 값일 수도 있다. 이 함수는 양쪽을 같은 척도(문자열)로 맞춰 비교 안정성을
    확보한다(`problem.py` validator 패턴의 공용 진입점).

    정규화 규칙:
      - `Enum` 멤버  → 그 `.value`(문자열). `SourceType.평가원` → `"평가원"`.
      - `str`        → 그대로 반환(이미 정규화된 값).
      - `None`       → `None` 보존(Optional 필드 미지정 — 신호 부재).
      - 그 밖의 타입 → `str(value)`로 강제(방어적 — 실무상 도달하지 않음).

    Args:
      value: 정규화할 값(Enum 멤버·문자열·None 등). `object`로 받아 호출처가 enum/문자열
        어느 쪽이든 그대로 넘길 수 있게 한다(call-overload·Any 회피).

    Returns:
      문자열 값(또는 입력이 None이면 None).

    이 함수가 `_source_value`·`_question_format_value`(RT)·`_exam_type_value`(수능)의
    공용 대체다 — 세 헬퍼는 모두 "enum이면 .value, None이면 None, 아니면 그대로"였다.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        # str-Enum이라 .value는 문자열이지만, 일반 Enum도 안전하게 다루려고 str()로 감싼다.
        return str(value.value)
    if isinstance(value, str):
        return value
    return str(value)


def source_value(problem: Problem) -> str:
    """`problem.source_type`을 *문자열 값*으로 정규화한다(use_enum_values=True 대응).

    `source_type`은 필수(non-Optional)라 항상 값이 있으므로 `str`을 반환한다(None 불가).
    내부적으로 `normalize_enum_value`를 쓰되, 필수 필드 계약을 타입으로 드러낸다.

    Args:
      problem: 출처를 읽을 문항(L1 `Problem`).

    Returns:
      `source_type`의 문자열 값(예: `"자체생성"`·`"평가원"`).
    """
    normalized = normalize_enum_value(problem.source_type)
    # source_type은 필수 필드라 None일 수 없다. mypy에 그 계약을 단언한다.
    assert normalized is not None  # noqa: S101 — 필수 필드 불변식(런타임 도달 불가)
    return normalized


def persona_fit(problem: Problem, persona: Persona) -> float:
    """`persona_fit`에서 주어진 페르소나의 적합도를 꺼낸다(키 문자열화 대응·없으면 0.0).

    use_enum_values=True 환경에서 `persona_fit`의 *키*가 `Persona` enum일 수도, 그 문자열
    값일 수도 있으므로 각 키를 *문자열 값*으로 정규화해 대상 페르소나와 대조한다. 적중이 없으면
    0.0(미평가 = 부적합). 선언 타입은 `dict[Persona, float]`이나 런타임 키가 문자열일 수 있어
    `normalize_enum_value`로 안전하게 정규화한다(call-overload·Any 회피).

    Args:
      problem: 적합도를 읽을 문항(L1 `Problem`).
      persona: 적합도를 조회할 대상 페르소나.

    Returns:
      `persona_fit[persona]`(0.0~1.0). 키가 없으면 0.0.

    이 함수가 RT·수능 두 모듈이 중복하던 `_persona_fit`의 공용 대체다(동작 동일).
    """
    target = persona.value
    for key, score in problem.persona_fit.items():
        if normalize_enum_value(key) == target:
            return score
    return 0.0


def is_exposable(problem: Problem) -> bool:
    """이 문항을 학생에게 *노출*해도 되는가 — 저작권 노출 게이트(L6 공용).

    `source_type`이 본문 미보유 출처(평가원/EBS/교과서, `METADATA_ONLY_SOURCES`)에 속하지
    *않으면* True(노출 가능), 속하면 False(노출 불가). 본문 미보유 출처는 구조 메타데이터
    참조 전용이라 학생에게 보일 발문·해설·선지가 없고, 그 본문 복제·영리이용은 저작권법으로
    금지되기 때문이다(CLAUDE.md 우선순위 #2 — 법적).

    L6의 모든 응용 모드(RT·수능·학교진도)는 적격성 판정에서 *대상 페르소나·진도 정합 등이
    아무리 맞아도* 이 게이트가 False면 즉시 차단한다(법적 우선순위가 교수학·UX보다 앞선다).

    Args:
      problem: 노출 가능성을 판정할 문항(L1 `Problem`).

    Returns:
      `source_type ∉ METADATA_ONLY_SOURCES`이면 True(노출 가능), 아니면 False(차단).

    use_enum_values=True 주의: `source_value`로 문자열 정규화 후 차단 집합의 문자열 값과
    대조한다(enum/문자열 양쪽 안전).
    """
    metadata_only_values = {s.value for s in METADATA_ONLY_SOURCES}
    return source_value(problem) not in metadata_only_values


def is_review_cleared(problem: Problem) -> bool:
    """이 문항이 *검수*를 통과했는가 — 운영 축 노출 게이트(L6 공용, PB-03).

    `is_exposable`(저작권·법적 축)과 **절대 합치지 않는다** — 이 함수는 검수(운영·정책 축)만
    본다. 두 축은 호출부에서 각각 독립된 `if`로 확인한다(설계 핵심, `problem_bank_gap_review_r2.md`
    노출 4단 중 ③단 "노출 적격"의 검수 절반).

    `review_status`가 `approved`일 때만 True — `None`(미평가)·`pending`(평가 대기)·`rejected`
    (기준 미달) 전부 fail-closed로 False다. §13.3: "모든 problem은 review_status=approved 후
    노출"(`ReviewStatus` enum docstring). 각인되는 값은 사람 인상이 아니라
    `harness/corpus_audit_eval.py`(`corpus_audit_eval`)의 측정 판정만이다(사람 입력 경로 0).

    **판정 권위 위임(CONT-01)**: 어떤 *값*이 검수 통과인가는 `schema.enums.is_review_status_cleared`
    한 곳에만 있고, 이 함수는 그 값 판정을 `Problem`에 적용하는 얇은 어댑터다. 빌드타임 경로
    (`harness/concept_assessment_index.py` — 개념 평가 재료 상속 후보 필터)는 `Problem`이 아니라
    코퍼스 JSONL dict를 다루므로 이 함수를 재사용할 수 없고, 대신 같은 값 판정 함수를 부른다.
    그렇게 해서 "런타임 노출 게이트"와 "빌드타임 상속 필터"가 **같은 한 줄**을 공유한다 — 한쪽만
    완화되는 기준 이원화를 구조적으로 막는다.

    Args:
      problem: 검수 상태를 판정할 문항(L1 `Problem`).

    Returns:
      `review_status == ReviewStatus.approved`이면 True, 그 외(`None`·`pending`·`rejected`)는
      False.
    """
    return is_review_status_cleared(problem.review_status)


__all__ = [
    "METADATA_ONLY_SOURCES",
    "is_exposable",
    "is_review_cleared",
    "normalize_enum_value",
    "persona_fit",
    "source_value",
]
