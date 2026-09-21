"""store.id_number_of — 슬러그 없는 ID 파싱 결함 (HARN-21 결함 ①).

`TASK_ID_RE`(models.py)는 슬러그가 **옵션**이라 `HARN-20`처럼 슬러그 없는 ID도 유효한
태스크 ID다. 그런데 구 `_ID_NUMBER_RE`는 캡처 그룹 뒤에 반드시 `-`가 와야 매치했다 —
슬러그 없는 ID는 `id_number_of`가 `None`을 돌려줬고, 그러면 `_taken_id_numbers`·
`_id_number_collisions`가 그 번호를 점유 목록에서 **누락**시켜 1선(`add`)·2선
(`validate`) 번호 충돌 검사를 양쪽 다 우회할 수 있었다.

이 파일은 `TASK_ID_RE`가 허용하는 전 형태(슬러그 있음/없음·접두 1~8자·번호 2자리
이상·슬러그 다단)에서 `id_number_of`가 정확히 `<PREFIX>-<번호>`를 뽑아내는지 표로
검증한다.
"""

from __future__ import annotations

import pytest
import store
from models import TASK_ID_RE


class TestTaskIdReAcceptsThreeDigitNumbers:
    """[HARN-97] TASK_ID_RE — 2자리(01~99)뿐 아니라 3자리(100~999, 선행 0 없이)도 유효.

    2026-09-09 실측: ARCH·EOS 두 접두가 99개 상한에 도달해 `--id EOS-100`이 형식
    검증 자체에서 거부됐다. 기존 2자리 ID는 전부 그대로 유효해야 한다(하위호환) —
    자릿수를 넓히되 "099" 같은 선행 0 3자리 표기는 "99"와 같은 번호를 가리키는
    두 번째 문자열이 되므로 금지한다.
    """

    @pytest.mark.parametrize(
        ("task_id", "expected_valid"),
        [
            ("EOS-99", True),  # 기존 2자리 — 하위호환 회귀 방지
            ("EOS-100", True),  # HARN-97 신설 — 3자리(선행 0 없음)
            ("EOS-999", True),  # 3자리 상한
            ("EOS-100-slug", True),  # 슬러그 동반 3자리
            ("EOS-1000", False),  # 4자리는 여전히 금지(HARN-97 acceptance③ — 999가 실제 상한)
            ("EOS-099", False),  # 선행 0 3자리 — "99"와 같은 번호의 모호한 표기, 금지
            ("EOS-9", False),  # 1자리 — 기존에도 무효
        ],
    )
    def test_format_validity(self, task_id: str, expected_valid: bool) -> None:
        assert bool(TASK_ID_RE.match(task_id)) == expected_valid, task_id

    def test_id_number_of_parses_three_digit_id(self) -> None:
        """[HARN-97 acceptance①] store.id_number_of가 3자리 ID도 정확히 추출한다 —
        이미 `\\d+`(자릿수 무관)라 이 정규식 자체는 바뀌지 않았음을 실측으로 고정."""
        assert store.id_number_of("EOS-100") == "EOS-100"
        assert store.id_number_of("EOS-100-auto-resync-workflow") == "EOS-100"

    def test_two_and_three_digit_ids_coexist_without_number_collision(self) -> None:
        """[HARN-97 acceptance②] EOS-43과 EOS-100이 같은 백로그에 공존해도
        번호 충돌 검사(store._id_number_collisions)가 서로 다른 번호로 정확히
        구분한다 — 자릿수 혼재가 충돌 판정을 깨지 않는다."""
        errors = store._id_number_collisions(["EOS-43-old-slug", "EOS-100-new-slug"])
        assert errors == []

    def test_two_and_three_digit_same_number_still_collides(self) -> None:
        """[HARN-97 acceptance②] 자릿수 확장 후에도 진짜 충돌(같은 번호, 다른 슬러그)은
        여전히 잡힌다 — 폭을 넓힌 것이 충돌 검사 자체를 무력화하지 않았음을 확인."""
        errors = store._id_number_collisions(["EOS-100-slug-a", "EOS-100-slug-b"])
        assert len(errors) == 1 and "EOS-100" in errors[0]


class TestIdNumberOfCoversSluglessIds:
    """수정 전: 슬러그 없는 ID가 전부 None → 번호 충돌 검사에서 누락됐다."""

    @pytest.mark.parametrize(
        ("task_id", "expected"),
        [
            # 슬러그 없음 (TASK_ID_RE의 슬러그-옵션 형태) — 구현 전엔 전부 None이었다.
            ("HARN-20", "HARN-20"),
            ("S2-04", "S2-04"),
            ("E1-99", "E1-99"),
            ("A-01", "A-01"),  # 접두 1자
            ("ABCDEFGH-02", "ABCDEFGH-02"),  # 접두 8자(TASK_ID_RE 상한)
            # 슬러그 있음 — 기존에도 통과했어야 하는 형태(회귀 방지)
            ("HARN-20-foo", "HARN-20"),
            ("HARN-20-foo-bar", "HARN-20"),
            ("S2-04-alpha", "S2-04"),
            # 규약을 벗어난 ID — 여전히 None(검사 대상 아님)
            ("not-a-task-id", None),
            ("", None),
        ],
    )
    def test_id_number_of_table(self, task_id: str, expected: str | None):
        assert store.id_number_of(task_id) == expected
