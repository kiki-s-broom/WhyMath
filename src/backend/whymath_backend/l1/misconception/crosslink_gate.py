"""오개념 crosswalk Gate Contract — 승인·적재 조건의 *단일 정본*(문서·코드 동일 관리).

crosswalk(kebab-id ↔ M-id) 매핑은 **사람 검수 산출물**이다 — 틀린 매핑은 오도된 리포트로 이어지므로
(CLAUDE.md 우선순위 #1·#3·`math_dsl_remediation_design.md` §1) 검수 없는 적재를 금지한다. 그 규칙이
그동안 `crosslink_review._promotion_violations` 인라인·`_DIRECT_MIN_CONFIDENCE`·`ReviewStatus`
Literal에 흩어져 있었고, `load_crosslinks`엔 게이트가 아예 없었다(임의 `{"crosslinks":[...]}`를 서명
없이 적재 — 우회 약점). 이 모듈은 그 규칙을 **하나로 모은 정본**이다(`docs/standards/crosswalk_gate_
contract.md`와 1:1·`test_crosslink_gate_contract`가 드리프트 동결). 수백~수천 건 규모로 커져도 운영
방식이 흔들리지 않게 승인 조건을 한곳에서 관리한다.

**두 게이트(같은 정본)**:
  - **promotion**(l4 승인분): `promotion_violations` — 승인 행 서명(reviewer·reviewed_on) 필수·
    직접매핑 승인은 confidence ≥ 임계·kebab_id는 카탈로그 실재·**직접매핑만 승인 가능**
    (부분매핑·개념겹침은 승인해도 기본 적재 금지 — MISC-63).
  - **load**(l1 로더 경계): `load_gate_violations` — 적재 행은 `method="manual"`이고 note에
    검수 서명 stamp가 있어야 하며 **link_type은 직접매핑**이어야 한다(candidate/embedding·미서명·
    비직접매핑 우회 거부).

**계층 규칙**: 이 모듈은 **l1**이라 l1 loader·l4 review가 모두 import한다(l4→l1 허용·역방향 금지).
카탈로그 멤버십은 **주입**(`known_kebab_ids`)해 계층 무관 순수를 유지한다(l1이 l4 `CATALOG_BY_ID`를
import하면 lint-imports 위반). 순수 술어는 raise하지 않고 위반 목록을 반환하며, 각 호출부가 자기
에러 타입으로 raise한다(promote=`CrosslinkReviewError`·load=`CrosslinkGateError`).
"""

from __future__ import annotations

import re
from collections.abc import Container, Sequence
from datetime import date
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

# ── 상수 (docs/standards/crosswalk_gate_contract.md 와 1:1·거버넌스 동결) ──────────────────
# 검수 상태 어휘 — pending(미검수)·approved(승인)·rejected(반려)·deferred(보류).
REVIEW_STATUSES: Final[tuple[str, ...]] = ("pending", "approved", "rejected", "deferred")
# 승인 상태(적재 대상) — 이 상태만 promote가 승격한다.
APPROVED_STATUS: Final[str] = "approved"
# 승인 행 필수 서명 필드 — 둘 다 있어야 승격(검수 책임 추적).
REQUIRED_SIGNATURE_FIELDS: Final[tuple[str, ...]] = ("reviewer", "reviewed_on")
# 직접매핑 승인 최소 신뢰도(초안 §0.2) — 미만은 "인접 오개념"이라 직접매핑 승격 금지.
DIRECT_MIN_CONFIDENCE: Final[float] = 0.6
# canonical 후보 자격 연결 의미(직접매핑) — schema CrosslinkType 어휘.
DIRECT_LINK_TYPE: Final[str] = "직접매핑"
# 적재 가능 method — 사람 채택 산출물만(candidate 도구의 embedding/standard_code는 미적재).
LOADABLE_METHOD: Final[str] = "manual"

# ── 기계 자동 거부(structural_reject·초인간 검증 §3.3) — 측정된 안전 자율 행동 ──────────────────
# 강등전(240/240·Wilson 하한 0.989)으로 *성취기준 가로지르는 오매핑 거부*가 측정된 구간에서만,
# 기계가 후보를 **자율 거부**한다(절대 승인 아님 — 승인은 인간 존치). 거부의 실패 모드는 보수적
# (correct 매핑을 놓쳐도 *누락*이지 오매핑 적재가 아님). 신뢰 조건: kebab이 문항에 충분히 등장해
# 역유도 성취기준이 신뢰할 만한 것(증거 하한). 미달·no_signal·agree는 전부 인간 폴백.
MACHINE_REJECT_METHOD: Final[str] = "structural_reject"
MACHINE_REJECT_REVIEWER: Final[str] = "machine"
MACHINE_REJECT_EVIDENCE_FLOOR: Final[int] = 20

# 서명 stamp 정본 — promote가 note에 찍고 load 게이트가 검증(단일 형식·드리프트 방지).
_SIGNATURE_PREFIX: Final[str] = "검수:"
# "검수:{reviewer} {YYYY-MM-DD}" 패턴 — reviewer(공백 아닌 시작)·ISO 날짜.
SIGNATURE_RE: Final[re.Pattern[str]] = re.compile(r"검수:\S.*\s\d{4}-\d{2}-\d{2}")


class CrosslinkGateError(ValueError):
    """crosswalk 게이트 위반 — 위반을 *전건 열거*한 메시지로 실패한다(조용한 누락 금지)."""


def sign(reviewer: str, reviewed_on: date) -> str:
    """검수 서명 stamp 정본 — `"검수:{reviewer} {ISO date}"`. promote가 승인 행 note에 병합한다."""
    return f"{_SIGNATURE_PREFIX}{reviewer} {reviewed_on.isoformat()}"


def is_signed(note: str | None) -> bool:
    """note에 검수 서명 stamp가 있는지 — load 게이트가 사람 검수 산출물임을 확인(우회 차단)."""
    return note is not None and SIGNATURE_RE.search(note) is not None


def non_direct_load_message(link_type: str) -> str:
    """비직접매핑 행의 적재 거부 사유 — promote·load 두 게이트가 같은 문구를 쓴다."""
    return (
        f"link_type='{link_type}'는 적재 불가 — 부분매핑·개념겹침은 승인해도 적재하지 않는다"
        f"(MISC-63). 예외 경로: 검수 큐에서 link_type을 '{DIRECT_LINK_TYPE}'으로 승격하고 "
        f"confidence ≥ {DIRECT_MIN_CONFIDENCE}를 기입한 뒤 재서명"
    )


def promotion_violations(
    *,
    kebab_id: str,
    mis_id: str,
    status: str,
    reviewer: str | None,
    reviewed_on: date | None,
    link_type: str,
    confidence: float | None,
    known_kebab_ids: Container[str],
    row_label: str = "",
) -> list[str]:
    """검수 큐 1행의 승격 규칙 위반 목록(순수·raise 안 함) — kebab 실재(전행)·서명·직접매핑 conf.

    `known_kebab_ids`는 호출부가 주입하는 카탈로그 kebab 집합(l1→l4 역방향 import 회피). `row_label`
    은 메시지 접두(예 `"[행 0] "`)로 호출부가 행 위치를 붙일 수 있게 한다.
    """
    where = f"{row_label}{kebab_id}→{mis_id}"
    violations: list[str] = []
    if kebab_id not in known_kebab_ids:
        violations.append(f"{where}: kebab_id가 L4 카탈로그에 없음 — 전사 왜곡 의심")
    if status != APPROVED_STATUS:
        return violations
    if reviewer is None or reviewed_on is None:
        violations.append(f"{where}: 승인 행에 검수 서명(reviewer·reviewed_on) 누락")
    if link_type != DIRECT_LINK_TYPE:
        # 적재 자격(MISC-63) — 부분매핑·개념겹침은 승인해도 기본 적재 금지. 예외 경로는 하나뿐이다.
        violations.append(f"{where}: {non_direct_load_message(link_type)}")
    if link_type == DIRECT_LINK_TYPE and (confidence is None or confidence < DIRECT_MIN_CONFIDENCE):
        violations.append(
            f"{where}: 직접매핑 승인은 confidence ≥ {DIRECT_MIN_CONFIDENCE} 필수"
            f"(현재 {confidence}) — 초안 §0.2 승격 금지"
        )
    return violations


def load_gate_violations(rows: Sequence[MisconceptionCrosslink]) -> list[str]:
    """적재 직전 행들의 load 게이트 위반 목록(순수·raise 안 함) — method=manual·서명 필수.

    로더(`load_crosslinks`)의 sanctioned 경계 방어다. promote 산출물은 전 행 `method="manual"`이고
    note에 검수 서명 stamp가 있어 통과하지만, candidate 도구 출력(method="embedding")·손수 만든
    미서명 `{"crosslinks":[...]}`는 거부된다(검수 우회·AI 자기승인 차단). 저수준 `Store.populate`는
    이 게이트를 거치지 않는다(합성 시딩 좌석) — 게이트는 로더 진입에만.
    """
    violations: list[str] = []
    for i, row in enumerate(rows):
        where = f"[행 {i}] {row.kebab_id}→{row.mis_id}"
        if row.method != LOADABLE_METHOD:
            violations.append(
                f"{where}: method='{row.method}'는 적재 불가 — 검수 승격(promote) 산출물"
                f"(method='{LOADABLE_METHOD}')만 적재한다(검수 우회 차단)"
            )
        if row.link_type != DIRECT_LINK_TYPE:
            # promote를 우회한 손수 만든 crosslinks JSON도 비직접매핑은 적재하지 못한다(MISC-63).
            violations.append(f"{where}: {non_direct_load_message(row.link_type)}")
        if not is_signed(row.note):
            violations.append(
                f"{where}: note에 검수 서명(검수:{{reviewer}} {{날짜}}) 없음 — "
                "사람 검수 산출물이 아님(promote --load 경유 필수)"
            )
    return violations


__all__ = [
    "APPROVED_STATUS",
    "CrosslinkGateError",
    "DIRECT_LINK_TYPE",
    "DIRECT_MIN_CONFIDENCE",
    "LOADABLE_METHOD",
    "MACHINE_REJECT_EVIDENCE_FLOOR",
    "MACHINE_REJECT_METHOD",
    "MACHINE_REJECT_REVIEWER",
    "REQUIRED_SIGNATURE_FIELDS",
    "REVIEW_STATUSES",
    "SIGNATURE_RE",
    "is_signed",
    "load_gate_violations",
    "non_direct_load_message",
    "promotion_violations",
    "sign",
]
