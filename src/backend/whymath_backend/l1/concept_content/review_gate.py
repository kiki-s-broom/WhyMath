"""개념 콘텐츠 검수 승격 Gate Contract — `ai_estimated → reviewed` 승인 조건의 단일 정본.

`review_status == "reviewed"`는 단순 표기가 아니라 **학생 노출 게이팅 기준**이다 —
`l1/concept_graph/retrieval.py`·`l1/atom_graph/retrieval.py`가 이 값으로 검색 히트를 거른다.
따라서 서명 없는 승격은 "메타데이터 부정확"이 아니라 **미검증 AI 콘텐츠의 학생 노출**이며,
CLAUDE.md 의사결정 우선순위 #1(학생 안전)·금기 "AI 자기승인 금지"(협상 불가)에 직접 걸린다.

그동안 그 규칙은 `concept_content_review_apply` docstring("사람이 검수한")에만 있었고 **코드가
검사하지 않았다** — 실측(2026-09-21): `reviewed_by` 누락·`"claude"`·빈 문자열 라벨 3건이
코퍼스와 DB에 전건 승격됐다. 이 모듈은 그 규칙을 코드로 옮긴 정본이며, 자매 경로인 오개념
crosswalk의 `l1/misconception/crosslink_gate.py`와 같은 형태다(순수 술어·위반 목록 반환).

**allowlist인 이유(금지 목록이 아니라)**: `reviewed_by`를 "AI 이름이면 거부"로 짜면 표기 변형
(`claude2`·`c1aude`)에서 그대로 뚫린다. 등재된 검수자만 통과시키면 개명으로 우회할 수 없다
(CLAUDE.md "금지 패턴 열거 대신 산출물 검사").

**한계(명시)**: 이 게이트가 막는 것은 *망각과 자기승인*이지 *위조*가 아니다 — 세션이
`reviewed_by: "kiki"`라고 적는 것을 로컬 CLI 계층에서 막을 방법은 없다. `backlog.py done`의
PR 증적 검사가 같은 한계를 명시한 선례와 동형이다. 위조 방어는 커밋 이력·PR 리뷰가 맡는다.

**계층 규칙**: 순수 술어만 두고 raise하지 않는다(호출부가 자기 에러 타입으로 처리). stdlib 외
의존이 없어 어느 계층에서 import해도 역방향 의존이 생기지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

# ── 승인 어휘 ────────────────────────────────────────────────────────────────────────
# 이 상태만 승격 대상이다. 다른 값(ai_estimated·rejected 등)은 코퍼스·DB를 건드리지 않는다.
APPROVED_STATUS: Final[str] = "reviewed"
# 승인 행 필수 서명 필드 — 둘 다 있어야 승격(검수 책임 추적).
REQUIRED_SIGNATURE_FIELDS: Final[tuple[str, ...]] = ("reviewed_by", "reviewed_at")

# ── 검수 권위 레지스트리 (CLAUDE.md "검증 권위 서열") ──────────────────────────────────
# ② 측정 통과 기계 게이트 — 결함 주입 강등전을 통과해 검출률이 측정된 판정자만 등재한다.
# 현재 **비어 있다**: 강등전(S4-16)이 2026-08-14 로컬 Ollama 실측에서 전 모델 탈락해
# (qwen3.5:27b 타임아웃 · qwen2.5:7b 오검출 100% · qwen2-math:7b 검출 58%/오검출 67%)
# 승격 권위를 가진 기계 판정자가 아직 없기 때문이다. 비어 있음 = fail-closed 기본값이며,
# 여기에 항목을 추가하려면 강등전 증적이 필요하다(거버넌스 테스트가 공백을 동결한다).
CERTIFIED_MACHINE_REVIEWERS: Final[tuple[str, ...]] = ()
# ③ 인간 폴백 — 등재된 사람 검수자. 도메인 파트너 영입 시 게이트 G-domain-partner 경유로 추가한다.
HUMAN_REVIEWERS: Final[tuple[str, ...]] = ("kiki",)


def known_reviewers() -> tuple[str, ...]:
    """승격 권위를 가진 검수자 전체 — 사람 검수자 + 강등전 통과 기계 판정자."""
    return tuple(HUMAN_REVIEWERS) + tuple(CERTIFIED_MACHINE_REVIEWERS)


def _normalize(handle: str | None) -> str:
    """검수자 핸들 정규화 — 앞뒤 공백 제거 + 소문자(대소문자 표기 차이로 거부되지 않게)."""
    return handle.strip().lower() if handle is not None else ""


def is_known_reviewer(handle: str | None) -> bool:
    """등재된 검수자인가 — allowlist 조회(개명 우회 불가)."""
    normalized = _normalize(handle)
    return bool(normalized) and normalized in {r.lower() for r in known_reviewers()}


def parse_reviewed_at(value: str | None) -> date | None:
    """검수 시각 파싱 — ISO 8601 날짜 또는 일시. 파싱 불가·부재는 None(호출부가 위반 처리).

    `2026-08-16T00:00:00Z`의 `Z`는 `datetime.fromisoformat`이 3.11부터 받지만, 저장소가
    지원하는 하한에서 흔들리지 않게 `+00:00`으로 바꿔 넘긴다(표기 차이로 정상 라벨이 거부되면
    그것대로 변별력 없는 게이트가 된다).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def promotion_violations(
    *,
    code: str,
    review_status: str,
    reviewed_by: str | None,
    reviewed_at: str | None,
    row_label: str = "",
) -> list[str]:
    """검수 라벨 1행의 승격 규칙 위반 목록(순수·raise 안 함).

    승격 대상(`review_status == "reviewed"`)이 아닌 행은 검사하지 않는다 — 코퍼스·DB를
    건드리지 않으므로 서명이 없어도 무해하다(거부·보류 라벨에 서명을 강요하면 검수자가
    게이트를 끄게 된다).
    """
    if review_status != APPROVED_STATUS:
        return []

    where = f"{row_label}{code}"
    violations: list[str] = []

    if not _normalize(reviewed_by):
        violations.append(
            f"{where}: 승인 행에 검수 서명(reviewed_by) 누락 — "
            "AI 자기승인 금지(CLAUDE.md 협상 불가), 승격 권위는 사람 검수 또는 "
            "강등전 통과 기계 판정자만"
        )
    elif not is_known_reviewer(reviewed_by):
        violations.append(
            f"{where}: 검수자 '{reviewed_by}'가 승격 권위 레지스트리에 없음 "
            f"(등재: {', '.join(known_reviewers()) or '(기계 판정자 없음)'}) — "
            "강등전으로 검출률이 측정된 판정자만 등재한다"
        )

    if parse_reviewed_at(reviewed_at) is None:
        violations.append(
            f"{where}: 승인 행에 검수 시각(reviewed_at·ISO 8601) 누락 또는 파싱 불가 "
            f"(현재 {reviewed_at!r}) — 검수 시점을 추적할 수 없는 승격 금지"
        )

    return violations
