"""발행 판 보호 — 발행된 판이 있는 문항의 *서빙 내용* 변경을 막는 판정 (EOS-195).

## 왜 이 모듈이 있는가

문항 판(`problem_version`)은 스냅숏이고 학생에게 서빙되는 원본은 라이브 `problem` 행이다. 발행 뒤
라이브 행을 고치면 EOS-47이 시도에 고정한 판의 payload가 학생이 실제로 푼 문항과 달라진다.
`l3/problem_publish_gate`의 `live_content_current` 검사는 *발행하는 순간*만 막는다. 그래서 발행 뒤
라이브 행을 바꾸는 **쓰기 경로 쪽**이 이 판정을 경유한다 — 호출자 세 곳:

  - `api/admin_cms._edit_block_reason` — 관리자 CMS 편집(`PATCH /v1/admin/cms/problem/...`)
  - `api/problems.patch_problem` — 콘텐츠 관리자 부분 수정(`PATCH /v1/problems/{id}`)
  - `l1/problem_bank/populate`의 upsert WHERE — 코퍼스 재적재(SQL이라 이 함수를 못 부르고 같은
    컬럼 상수를 쓴다)

처분(차단/자동 새 초안/표지만)의 근거와 수정 절차(판 폐기 → 수정 → 새 판 발행)는 EOS-195 태스크와
`l3/problem_publish_gate` docstring에 있다.

## 이 모듈의 경계

- **판정만 한다**(순수 — DB·세션·ORM import 없음). 읽는 것은 문항 객체의 속성뿐이라 ORM 행과
  `schema.Problem` 둘 다 받는다.
- **판 축을 모르는 척하지 않되, 문항 노출 경로가 판 모듈을 import하지 않게 한다**(AST 동결 B2:
  `api/problems.py`는 `problem_version`·`version_header`·`problem_publish_gate` 이름을 가진 모듈을
  import할 수 없다). 그래서 이 파일은 그 세 이름 어느 것도 모듈 경로에 담지 않는다.
- **서빙 내용 필드 목록(`SERVED_CONTENT_FIELDS`)은 `snapshot_payload`가 읽는 문항 속성과
  같아야 한다**
  — 두 곳이 갈라지면 "게이트가 보는 내용"과 "여기서 막는 내용"이 어긋난다.
  `tests/backend/db/test_published_edit_guard.py`가 `snapshot_payload`의 AST와 대조해 고정한다.
"""

from __future__ import annotations

from typing import Any, Final

#: 판 payload의 원천이 되는 문항 속성 — `l3/problem_publish_gate.snapshot_payload`가 읽는 것과 동일.
#: (`stem_hash`·`answer_hash`는 발문·정답에서 파생되므로 원천이 아니다.)
SERVED_CONTENT_FIELDS: Final[tuple[str, ...]] = (
    "source_type",
    "subject",
    "curriculum_version",
    "unit_codes",
    "question_format",
    "answer_format",
    "points",
    "question_text",
    "choices",
    "answer",
    "answer_explanation",
    "difficulty_overall",
)

#: 발행 포인터 컬럼명 — 적재기·CMS·부분 수정이 같은 이름을 본다.
POINTER_FIELD: Final[str] = "problem_version_id"

PUBLISHED_EDIT_BLOCKED_MESSAGE: Final[str] = (
    "발행된 판이 있는 문항입니다. 제자리 수정은 학생이 푼 판과 문항을 갈라놓습니다 — "
    "판을 먼저 폐기한 뒤 수정하고 새 판으로 다시 발행하세요."
)

POINTER_OWNED_MESSAGE: Final[str] = (
    "발행 포인터(problem_version_id)는 발행 게이트만 바꿀 수 있습니다 — "
    "수정 요청으로 바꿀 수 없습니다."
)


def has_published_version(problem: Any) -> bool:
    """발행 포인터가 채워진 문항인가(=서빙 기준 판이 있다)."""
    return getattr(problem, POINTER_FIELD, None) is not None


def changed_served_fields(before: Any, after: Any) -> tuple[str, ...]:
    """수정 전·후 사이에 값이 달라진 서빙 내용 필드 이름(정렬). 값은 돌려주지 않는다.

    비교는 `==`다 — 같은 모양의 두 객체(`schema.Problem` 둘, 또는 ORM 행 둘)를 넘기는 것이 전제다.
    왕복(GET 본문을 그대로 되돌려 보내는 PATCH)은 값이 같으므로 빈 튜플이다.
    """
    return tuple(
        sorted(
            name
            for name in SERVED_CONTENT_FIELDS
            if getattr(before, name, None) != getattr(after, name, None)
        )
    )


__all__ = [
    "POINTER_FIELD",
    "POINTER_OWNED_MESSAGE",
    "PUBLISHED_EDIT_BLOCKED_MESSAGE",
    "SERVED_CONTENT_FIELDS",
    "changed_served_fields",
    "has_published_version",
]
