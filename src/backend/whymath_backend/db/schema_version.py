"""기동 시 스키마 버전(alembic head) 일치 가드 — SEC-03.

**왜 필요한가**: SEC-01의 프로덕션 fail-closed 게이트는 *암호화 키 부재*만 막고 **마이그레이션
미적용은 막지 않는다**. SEC-02 실측(2026-07-27)에서 그 조합이 실물로 확인됐다 — 대상 DB가
`f3a4b5c6d7e8`(2026-06-30)에 머물러 `dialogue_turn.content_encrypted` 컬럼 자체가 없었다.
키만 설정되고 스키마가 뒤처지면 암호화 write가 런타임에 터지거나, 배포 순서에 따라 조용히
어긋난다. 그 구멍을 기동 시점으로 끌어올린다(첫 학생 요청이 아니라 부팅에서 드러나게).

**뒤처짐과 앞섬을 구분한다**: 엄격 동일성만 보면 *롤백을 막는다* — 코드만 되돌리고 DB는 앞선
상태로 두는 것이 정상 롤백 시나리오인데, 동일성 가드는 그 정상 상태에서 부팅을 거부해 **가드
자체가 장애 원인**이 된다. 그래서 판정을 셋으로 나눈다:

  - `MATCH`  — 적용 head == 코드 기대 head. 정상.
  - `BEHIND` — 적용 head가 `KNOWN_REVISIONS` 안의 *이전* 리비전(또는 미적용). **위험**: 코드가
    기대하는 컬럼이 DB에 없을 수 있다 → 프로덕션 추정 환경에서 기동 거부.
  - `AHEAD`  — 적용 head를 코드가 *모른다*. 코드보다 앞선 스키마(롤백 중)로 보고 **경고만**
    한다. 추가 컬럼은 대체로 무해하고, 여기서 막으면 롤백이 불가능해진다.

**왜 상수인가**: wheel은 `packages = ["whymath_backend"]`로 빌드돼 `alembic/versions/`가 배포
이미지에 **없다**. 런타임이 마이그레이션 파일을 읽는 설계는 성립하지 않는다. 그래서 리비전
목록을 패키지 안 상수로 두고, 실제 alembic 이력과 어긋나면 실패하는 **동결 테스트**가
`tests/backend/db/test_schema_version_guard.py`에서 표류를 막는다(인프로세스 이중 회계).
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("whymath.db.schema_version")

__all__ = [
    "EXPECTED_ALEMBIC_HEAD",
    "KNOWN_REVISIONS",
    "SchemaVersionVerdict",
    "classify_applied_head",
    "read_applied_heads",
    "verify_schema_version",
]

# alembic 이력의 base→head 위상 순서. 동결 테스트가 실제 `ScriptDirectory.walk_revisions()`와
# 대조하므로 수기 편집은 즉시 실패한다. 마이그레이션 추가 시 이 목록도 갱신한다(테스트가 알려줌).
KNOWN_REVISIONS: tuple[str, ...] = (
    "4c6d083dfeef",
    "1551744048aa",
    "bb30b816083d",
    "a1b2c3d4e5f6",
    "b2c3d4e5f6a7",
    "c3d4e5f6a7b8",
    "d4e5f6a7b8c9",
    "e5f6a7b8c9d0",
    "f6a7b8c9d0e1",
    "a7b8c9d0e1f2",
    "b8c9d0e1f2a3",
    "c9d0e1f2a3b4",
    "d0e1f2a3b4c5",
    "e1f2a3b4c5d6",
    "f2a3b4c5d6e7",
    "a3b4c5d6e7f8",
    "b5c6d7e8f9a0",
    "c6d7e8f9a0b1",
    "d7e8f9a0b1c2",
    "e8f9a0b1c2d3",
    "f9a0b1c2d3e4",
    "a0b1c2d3e4f5",
    "b1c2d3e4f5a6",
    "c2d3e4f5a6b7",
    "d3e4f5a6b7c8",
    "e4f5a6b7c8d9",
    "f5a6b7c8d9e0",
    "a6b7c8d9e0f1",
    "b7c8d9e0f1a2",
    "c8d9e0f1a2b3",
    "d9e0f1a2b3c4",
    "e0f1a2b3c4d5",
    "f1a2b3c4d5e6",
    "a2b3c4d5e6f7",
    "b3c4d5e6f7a8",
    "c4d5e6f7a8b9",
    "d5e6f7a8b9c0",
    "e6f7a8b9c0d1",
    "f7a8b9c0d1e2",
    "a8b9c0d1e2f3",
    "b9c0d1e2f3a4",
    "c0d1e2f3a4b5",
    "d1e2f3a4b5c6",
    "e2f3a4b5c6d7",
    "f3a4b5c6d7e8",
    "a4b5c6d7e8f9",
    "a5b6c7d8e9f0",
    "b6c7d8e9f0a1",
    "c7d8e9f0a1b2",
    "d8e9f0a1b2c3",
    "e9f0a1b2c3d4",
    "f0a1b2c3d4e5",
    "0a1b2c3d4e5f",
    "a1b2c3d4e5f0",
    "b2c3d4e5f0a1",
    "c3d4e5f0a1b2",
    "c3d4e5f0a1b3",
    "d4e5f0a1b3c4",
    "e5f0a1b3c4d5",
    "f0a1b3c4d5e6",
    "a2b3c4d5e6f0",
    "b3c4d5e6f0a1",
    "c4d5e6f0a1b2",
    "d5e6f0a1b2c3",
    "e6f1a2b3c4d5",
    "f1a2b3c4d5e7",
    "a2b3c4d5e6f1",
    "a9b8c7d6e5f4",
    "b4c5d6e7f0a2",
    "c5d6e7f0a2b3",
    "3702d8671074",
    "d6e7f0a2b3c4",
    "db8ae6d2d91c",
    "090d254a5d43",
    "c6d7e8f1a2b4",  # S4-09 solution_paths 신설 + problem_step additive 6컬럼
    "374fb620de9e",  # MISC-04: misconception_relation (caused_by·variant_of·개념그래프 격리)
    "d1e2f3c4b5a6",  # S3-32: dialogue.review_turns_remaining (Polya 돌아보기 턴 카운터)
    "e07b1324d1d4",  # LIC-01: Rights & Provenance Infrastructure MVP
    "b8e76fe238d0",  # EOS-3: Achievement Standard lifecycle expansion
    "fcfdfc277348",  # CUR-07: Achievement Standard evaluation criteria codes + level unit
    "899ae0efbb8b",  # CUR-10: Curriculum Framework / Version tables
    "fad7f750090d",  # CUR-16: concept_edge prerequisite 메타 확장
    "d7e8f1a2b4c6",  # S4-10 solution_paths.gen_meta — 다중 풀이 생성 주관 메타(ai_estimated)
    "8f0b8e906362",  # EOS-32: answer_submission — attempt 내 다회 제출 시퀀스 정규화
    "0e148995e6e9",  # EOS-45: hint_usage — 힌트 횟수·레벨·열람시간 1급 데이터화
    "a926d39f126a",  # EOS-46: student_solution_step — 학생 풀이 step 정규 기록(ADR-002)
    "c9bc2555282e",  # EOS-48: event_time/ingested_at 분리 + active/idle 실측 좌석(3테이블 ALTER)
    "84c782415837",  # EOS-54: review_timer_event — HIT 검수 타이머 이벤트 계측기
    "f4b2d8c1a3e5",  # EOS-55: generation_log 재현 좌석 5컬럼(prompt_version·seed·스냅샷·cu_slug)
    "d4a71c0f9b32",  # EOS-57: attempt_event.skill_ids[] 좌석 + event_type_enum '문제시도'
    "e7c3b9a15f24",  # EOS-71: problem 격리 좌석 2컬럼 + review_status_enum 'quarantined'
    "b8d3f6a91c24",  # EOS-97: generation_log.run_id — 리콜 조인 축 + idx_generation_run_id
    "c1a5e07b4d38",  # EOS-99: generation_log 프롬프트 캐시 2종(cache_read/creation_input_tokens)
    "d2f4a68b91e7",  # MISC-20: misconception_hypothesis.deactivated_reason — 해소율 정직화 축
    "e3b5c79d02f8",  # MISC-20: evidence_links.provenance — 해소 판정의 출처 축(가중치 추론 폐기)
    "19149e92d368",  # SEC-33 ⑥: problem_attempt.ingested_at server_default(신규 행 좌석 보장)
    "f2662166a661",  # SEC-27: job_ownership — 비동기 QUALITY 작업 소유권(job_id→user_id)
    "4c6dfb1527a9",  # SEC-29: privacy_audit.resource_type/resource_id/action — 콘텐츠CUD 감사
    "3f5c83f51246",  # SEC-31: 학생 답안/풀이 3테이블 봉투 암호화(problem_attempt·
    # answer_submission·student_solution_step 8쌍 16컬럼 + expression nullable 완화)
    "67cf48ad3bce",  # EOS-49: concept_version 테이블(Concept 좌석 4번째) + concept.
    # current_published_version_id(§6.4) + PUBLISHED 불변성 트리거(§7)
    "a7d41c9e0b52",  # EOS-103: learner_state 테이블(LearnerState 좌석 2번째) — 학습자
    # 현재 상태 1행 + 진단 완료 시 자동 생성 계보(provisioned_at/by·updated_at·revision)
    "5a7c31d9e0b4",  # EOS-105: learning_state_transition(학습 상태 전이 append-only 원장 ·
    # LearnerState 좌석 3번째 테이블) + learning_state_enum·learning_state_trigger_enum.
    # 병합 정정(2026-09-17): 두 PR이 같은 부모(67cf48ad3bce) 위에 각자 리비전을 얹어 head가
    # 둘이 될 뻔했다 — EOS-103이 먼저 머지됐으므로 이 리비전의 down_revision을 a7d41c9e0b52로
    # 재지정해 체인을 직렬로 되돌렸다(단일 head 유지).
    "c1f5a8b2d740",  # EOS-108: concept/skill_mastery_history.attempt_id(멱등 키) + 부분 유니크
    # 인덱스 2종. 같은 시도의 숙달 이중 반영을 DB가 막는다(KPI 2 State Integrity).
)

EXPECTED_ALEMBIC_HEAD: str = KNOWN_REVISIONS[-1]


class SchemaVersionVerdict(str, Enum):
    """스키마 버전 판정 — 이름이 곧 대응이다."""

    MATCH = "match"
    BEHIND = "behind"
    AHEAD = "ahead"


def classify_applied_head(applied: str | None) -> SchemaVersionVerdict:
    """적용된 head를 코드 기대치와 대조해 판정한다(순수 함수 — DB 무관·단위 시험 가능).

    `applied=None`(alembic_version 행 없음 = 한 번도 마이그레이션 안 됨)은 `BEHIND`다 —
    스키마가 아예 없는 것이 뒤처짐의 극단이다.
    """
    if applied == EXPECTED_ALEMBIC_HEAD:
        return SchemaVersionVerdict.MATCH
    if applied is None or applied in KNOWN_REVISIONS:
        return SchemaVersionVerdict.BEHIND
    return SchemaVersionVerdict.AHEAD


async def read_applied_heads(session: Any) -> tuple[str, ...]:
    """DB `alembic_version`에 적용된 리비전 목록을 읽는다(정렬 — 판정 재현성).

    분기 이력이면 여러 행이 될 수 있어 튜플로 돌려준다. 단일 head 프로젝트에선 0 또는 1개다.
    """
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    return tuple(sorted(row[0] for row in result.all()))


async def verify_schema_version(settings: Any) -> None:
    """기동 가드 — 스키마가 코드보다 뒤처졌으면 프로덕션 추정 환경에서 기동을 거부한다.

    개발·CI에서는 경고만 남긴다(막으면 아무도 못 돌린다 — SEC-01 fail-closed와 동일한 변별).
    확인 자체가 실패하면(DB 미도달·권한 부족 등) *통과로 위장하지 않고* 프로덕션에서는 거부한다
    — "측정 실패"를 "정상"으로 바꾸지 않는다는 규칙의 적용이다. 로그에는 예외 **타입명**을
    포함한다(침묵 실패 금지·시크릿·필드값 제외).

    Raises:
        RuntimeError: prod 추정 환경에서 스키마가 뒤처졌거나 확인에 실패한 경우.
    """
    from whymath_backend.config import is_production_like
    from whymath_backend.db.session import get_sessionmaker

    production_like = is_production_like(settings)

    # 타임아웃 필수 — 없으면 *패킷이 드롭되는* DB 호스트(방화벽·잘못된 주소)에서 부팅이 무한
    # 대기한다(연결 거부는 즉시 끝나지만 블랙홀은 안 끝난다 — 2026-07-28 실측: 30s 관찰 상한
    # 초과). `ping_device_store_health`가 같은 이유로 이미 이 노브를 쓴다(슬라이스 31) — 새 축을
    # 만들지 않고 재사용한다. 타임아웃 초과는 아래 except가 "확인 불가"로 받아 프로덕션에선 거부.
    timeout_seconds = float(getattr(settings, "device_store_health_check_timeout_seconds", 5.0))

    try:
        async with asyncio.timeout(timeout_seconds):
            sessionmaker = get_sessionmaker(settings)
            async with sessionmaker() as session:
                applied_heads = await read_applied_heads(session)
    except Exception as exc:
        message = (
            f"스키마 버전을 확인하지 못했습니다({type(exc).__name__}) — "
            f"기대 head={EXPECTED_ALEMBIC_HEAD}. DB 도달성·`alembic_version` 접근 권한을 "
            "확인하세요."
        )
        if production_like:
            raise RuntimeError(message) from exc
        logger.warning("%s 개발 환경이라 기동은 계속합니다.", message)
        return

    # 분기 이력이면 다중 head — 하나라도 뒤처지면 뒤처짐으로 본다(가장 보수적인 판정).
    applied = applied_heads[0] if len(applied_heads) == 1 else None
    if len(applied_heads) > 1:
        verdict = (
            SchemaVersionVerdict.MATCH
            if EXPECTED_ALEMBIC_HEAD in applied_heads
            else SchemaVersionVerdict.BEHIND
        )
    else:
        verdict = classify_applied_head(applied)

    if verdict is SchemaVersionVerdict.MATCH:
        return

    applied_desc = ", ".join(applied_heads) if applied_heads else "(미적용)"
    if verdict is SchemaVersionVerdict.AHEAD:
        logger.warning(
            "DB 스키마가 코드보다 앞섭니다 — 적용=%s / 코드 기대=%s. 롤백 중일 수 있어 "
            "기동은 계속합니다(앞선 스키마의 추가 컬럼은 이 코드가 쓰지 않습니다).",
            applied_desc,
            EXPECTED_ALEMBIC_HEAD,
        )
        return

    message = (
        f"DB 스키마가 코드보다 뒤처졌습니다 — 적용={applied_desc} / 코드 기대="
        f"{EXPECTED_ALEMBIC_HEAD}. 코드가 기대하는 컬럼이 DB에 없을 수 있습니다"
        "(예: 대화 봉투 암호화 컬럼 부재 시 미성년 데이터 저장이 실패하거나 어긋납니다). "
        "`alembic upgrade head`를 먼저 적용하세요."
    )
    if production_like:
        raise RuntimeError(message)
    logger.warning("%s 개발 환경이라 기동은 계속합니다.", message)
