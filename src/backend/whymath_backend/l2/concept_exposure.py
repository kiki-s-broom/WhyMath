"""학생 개념 노출 기록 — 어떤 개념을 언제 보았는가 (PED-17 A1).

C안 안전장치 6번 "모든 노출을 기록한다"의 쓰기 지점이다. 킬스위치가 개념을 회수할 때 "그 개념을 본
학생이 몇 명인가", D5 단계적 공개의 24시간 판정이 "이 개념을 본 학생 수"를 이 기록에서 읽는다.

────────────────────────────────────────────────────────────────────────────
가명 학생 ID — 이름도 원본 user_id도 저장하지 않는다
────────────────────────────────────────────────────────────────────────────
`student_pseudonym`은 키드 해시(HMAC-SHA256 hexdigest 64자)다. 서버 시크릿 없이는 역산할 수 없고,
서버는 같은 `user_id`로 다시 계산해 학생 단위 조회·삭제를 할 수 있다(삭제 요청 대응 가능).
`session_user_binding`(SEC-24)과 같은 계열이지만 **세션이 입력에 없다** — 같은 학생의 여러 학습
세션이 같은 가명으로 묶여야 "개념을 본 서로 다른 학생 수"를 셀 수 있기 때문이다. 도메인 프리픽스를
따로 두어 세션 바인딩·토큰 서명과 입력 도메인을 분리한다.

**키 로테이션 한계(명시)**: 키(`jwt_secret_key`)를 바꾸면 이후 노출은 새 가명으로 기록돼 같은 학생이
둘로 센다. 로테이션은 액세스 토큰도 무효화하는 드문 사건이고, 전용 가명화 키 분리는 A1 범위 밖이다.

────────────────────────────────────────────────────────────────────────────
`ai_label_shown` — 사실만 적는다
────────────────────────────────────────────────────────────────────────────
이 값은 "그 응답이 AI 라벨을 담았는가"의 사실이다. 호출자가 명시해야 하고 기본값이 없다. 라벨을
화면에 싣는 기능은 A1이 만들지 않으므로 지금 호출 지점(`api/study.py`)은 False를 넘긴다 — 없는
라벨을 있다고 적지 않는다. 라벨 기능이 착지하면 그 지점이 이 값을 바꾼다(보고서 "다음 작업" 참조).

계층: L2. 의존은 `db/models`·`config`뿐이다. flush·커밋은 호출자가 한다(처치 기록과 같은 트랜잭션).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import Settings
from whymath_backend.db.models.concept_lifecycle_log import ConceptExposureEvent

# HMAC 도메인 프리픽스 — jwt_secret_key를 토큰 서명·세션 바인딩과 공유하므로 입력 도메인을 분리한다
# (교차 용도 위조 차단). 스킴을 바꾸면 v2로 올려 구분한다.
_PSEUDONYM_DOMAIN = "whymath-concept-exposure-pseudonym-v1"


def student_pseudonym(user_id: uuid.UUID, *, settings: Settings) -> str:
    """학생 가명 ID — 키드 해시(HMAC-SHA256 hexdigest·64자).

    이름·원본 user_id는 어디에도 남지 않는다.
    """
    key = settings.jwt_secret_key.get_secret_value().encode()
    msg = f"{_PSEUDONYM_DOMAIN}:{user_id}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


async def record_concept_exposure(
    session: AsyncSession,
    *,
    concept_code: str,
    user_id: uuid.UUID,
    settings: Settings,
    ai_label_shown: bool,
) -> ConceptExposureEvent:
    """노출 1건을 세션에 추가한다(`add`만 · flush·커밋은 호출자).

    `record_pedagogy_treatment`와 같은 관례다 — 호출자가 처치 기록과 함께 한 번에 커밋하므로 둘 중
    하나만 남는 중간 상태가 없다. 형식 위반(CHECK)은 커밋 시점에 드러난다.

    `concept_code`는 학생이 실제로 본 `concept_content` 행의 code다(역조회면 요청 원자 code가 아니라
    서빙 행 code). 학생이 아무것도 보지 못한 응답(404)에는 호출하지 않는다.
    """
    event = ConceptExposureEvent(
        concept_code=concept_code,
        student_pseudonym=student_pseudonym(user_id, settings=settings),
        ai_label_shown=ai_label_shown,
    )
    session.add(event)
    return event


__all__ = ["record_concept_exposure", "student_pseudonym"]
