"""HintUsage — attempt 내 힌트 사용 1급 기록의 백엔드 계약 모델(Pydantic) (EOS-45).

설계 정본: `docs/architecture/32_learning_history.md` §4(HintUsage — "무힌트 20초 정답과 힌트
3회 4분 정답의 숙련도 해석 구분"). 현행 `problem_attempt.used_hint`는 불리언 1개라 힌트 *횟수·
레벨·열람시간*이 손실된다 — 이 모델이 힌트 사용 각 건을 정규화한다. **used_hint의 대체가
아니라 병행**이다(기존 소비자 `l2/learning_metrics_rollup.AttemptFact.used_hint` 불변).

이 Pydantic 모델은 검증·API 계약이고, 영속 매핑은 `db/models/hint_usage.py`(ORM)가 별도로
세운다 — `from_schema`/`to_schema` seam(`answer_submission.py` 동일 패턴·EOS-32 관례).

설계 판단(근거 병기):
  - `hint_id` — **느슨참조**(FK 아님). 실측(2026-08-30): 힌트 정본 테이블이 레포에 없다
    (`db/models` 전수 grep에서 hint 컬럼은 `used_hint`뿐·`hint_id` 심볼 0건) — 힌트는 l4
    코치(`hint_deferral.decide_hint_level` + LLM)가 *동적 생성*하며 영속 정체성이 없다.
    없는 테이블에 FK를 만들지 않는다(FK 날조 금지). 식별자가 실재하는 경로(예: GenerationLog
    id·콘텐츠 주소 해시)에서만 채우고, 없으면 None(정직 — 가짜 id 생성 금지).
    **현황 명시(ARCH-39 · 2026-09-06 · 판정 기준 main 3f2b39c1)**: `hints` 좌석은 지금도
    없으며(ORM·마이그레이션 0건), 신설은 `S4-11-hint-content-generation`(P0·todo)이 소유한다
    (`canonical_entity_model_v1.md` §3-B). 그러므로 이 컬럼은 **언젠가 FK가 될 수 있는 자리**이며,
    그 전환 판단(FK로 조일지)도 S4-11의 몫이다. 그때까지는 위에 적은 *실재하는 식별자 경로*만
    담는다. **현재 writer는 0건**이다(서빙 코드 전수 — 정의·주석 외 대입 0). 즉 이 필드는 지금
    *구조만 있고 흐르지 않는다* — "작동 신호 없는 알고리즘 부착 금지"(CLAUDE.md)에 따라 그 사실을
    여기 명시해 둔다.
  - `hint_level` 1~4 — 폐쇄 범위의 정본은 `l4.hint_deferral.HintLevel`(Literal[1,2,3,4])이다.
    schema는 l4를 import할 수 없으므로(7계층 단방향) 수치를 복제해 ge=1·le=4로 구속한다
    (정본 변경 시 여기도 갱신 — 주석 명시 복제).
  - `view_duration_ms` — **nullable**(실측 판단): 열람 시간은 클라 계측인데 종료 신호(이탈·앱
    강제 종료·백그라운드 전환)가 오지 않는 미확정 케이스가 구조적으로 존재한다. None=미측정
    (0으로 날조하면 "0ms 열람"과 구분 불가 — `learning_metrics_rollup.effective_seconds`의
    "미상은 None·날조 금지" 방침과 동형).
  - `raw` 성격의 자유 텍스트 필드가 없어 str_strip 판단 대상이 없다(EOS-32 P2와 달리 hint_id는
    식별자 — 기본값(strip 없음) 유지).

개인정보 메모(CLAUDE.md·`activity.py` 방침): 힌트 사용 이력은 학습 행동 데이터(미성년)다 —
privacy 3종 배선(erasure·retention·export)은 32_learning_history §11이 acceptance로 강제한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class HintUsage(BaseModel):
    """힌트 사용 1건 — attempt 안에서 학생이 힌트를 실제로 연 기록(요청 시각순).

    한 행 = 한 attempt(`attempt_id`)에서 학생(`user_id`)이 힌트 1개를 연 사건이다. 순번
    컬럼은 두지 않는다 — `requested_at`(서버 시각)이 자연 순서다(answer_submission의
    sequence_no와 달리 힌트는 "몇 번째 제출" 같은 프로토콜 순번 의미가 없다).
    """

    model_config = ConfigDict(extra="forbid")

    # ===== 기본 식별 =====
    hint_usage_id: uuid.UUID = Field(default_factory=uuid4, description="힌트 사용 PK (UUID)")
    attempt_id: uuid.UUID = Field(
        description="소속 시도 FK (problem_attempt 참조·required — attempt 없는 힌트 사용은 "
        "없다. DB는 (attempt_id, user_id) 복합 FK로 소유 일치 강제 — EOS-32 PR #902 P1 관례)"
    )
    user_id: uuid.UUID = Field(
        description="학생 FK (user_profile 참조·required — pseudonymous user_id만·"
        "32_learning_history §11)"
    )

    # ===== 힌트 식별·수준 =====
    hint_id: str | None = Field(
        default=None,
        max_length=200,
        description="열람한 힌트의 식별자(느슨참조 — 힌트 정본 테이블 부재 실측·FK 아님). "
        "식별자가 실재하는 경로(생성 로그 id 등)만 채움. None = 동적 생성 힌트(식별자 없음)",
    )
    hint_level: int = Field(
        ge=1,
        le=4,
        description="힌트 노출 수준 1~4(1=방향·4=전체 풀이). 폐쇄 범위 정본은 "
        "l4.hint_deferral.HintLevel(Literal[1,2,3,4]) — 계층상 import 불가라 수치 복제",
    )

    # ===== 시간·계측 =====
    requested_at: datetime | None = Field(
        default=None,
        description="힌트 요청(열람 시작) 시각(서버 기준 — DB DEFAULT NOW()). None = DB가 채움",
    )
    view_duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="열람 시간(ms·클라 계측). None = 미측정(종료 신호 부재 — 이탈·강제 종료 등. "
        "0으로 날조 금지: '0ms 열람'과 '미측정'은 다른 사실)",
    )


__all__ = ["HintUsage"]
