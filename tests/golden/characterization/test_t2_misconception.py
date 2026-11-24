"""T2 특성화 테스트(S26 · 다섯 걸음 ② · 인용 F-05) — 옛 오개념 로더의 지금 동작을 고정한다.

옛 `whymath_backend.l1.misconception.catalog_loader.load_misconceptions`를 **옛 자리에서 그대로** 부른다.
이 함수는 원래 DB 적재기(`misconception_catalog` 테이블 upsert)다. 인자 `store`에 가짜 저장소를 넣어
DB 없이 부르고, 저장소가 받은 검증된 행(`schema.MisconceptionCatalog`)을 출력으로 본다.
지금 동작이 맞는지는 묻지 않는다 — 바뀌지 않는지만 본다.

- 입력 10개 = 오개념 ID 10개(`golden/data/misconceptions_lf.json`의 앞 10건 · 일차함수분 8 + 부호 2)의
  코퍼스 행. 출력 10개 = 핵심 칸 7개를 고정한다.
- 결정성: 같은 입력 100회 → 같은 출력.
- 매칭 함수(틀린 답 → 오개념 ID)는 없다. 옛 `wrong_answer_signature_table.py`의 규칙 10개는 모두
  미분(도함수·극값) 문항용이고 일차함수 오개념 ID가 하나도 없다. `resolve.py`는 성취기준·개념 연결을
  푸는 함수라 답을 보지 않는다(S26 보고 · HARVEST T2 경계).
- 옛 모듈은 이 테스트에서만 import한다. 골든 코드(`src/backend/golden/`)는 import하지 않는다
  (import-linter 계약 `golden-no-legacy`의 대상은 `golden` 패키지뿐이다 · 이 모듈은 LEGACY_MANIFEST에 있다).
- 마지막 테스트는 골든 자료 파일이 옛 로더의 출력과 같은 글을 담고 있는지(추출이 원문을 바꾸지 않았는지) 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from golden.sim import errors
from whymath_backend.l1.misconception import catalog_loader

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"
GOLDEN_LF = REPO_ROOT / "golden" / "data" / "misconceptions_lf.json"

# 입력 ID 10개 — 골든 자료 파일 순서의 앞 10건(나머지 1건 M0548은 마지막 대조 테스트가 본다)
INPUT_IDS: tuple[str, ...] = (
    "M0034",
    "M0035",
    "M0036",
    "M0037",
    "M0409",
    "M0567",
    "M0568",
    "M0569",
    "M0001",
    "M0002",
)

# 출력 10개 — (mis_id, canonical_statement, student_wrong_thinking, distractor_rule, error_type,
# standard_code, severity). 2026-11-24 이 세션에서 옛 함수를 불러 얻은 값 그대로다.
EXPECTED: tuple[tuple[str | None, ...], ...] = (
    (
        "M0034",
        "기울기",
        "y절편을 기울기로 착각",
        "y=2x+3 기울기 3 배치",
        "공식혼동",
        "[9수02-15]",
        "local",
    ),
    (
        "M0035",
        "일차함수 그래프",
        "음의 기울기 방향 혼동",
        "증가·감소 반대",
        "해석오류",
        "[9수02-15]",
        "blocking",
    ),
    ("M0036", "절편", "x절편과 y절편 혼동", "좌표 바꿔 배치", "공식혼동", "[9수02-15]", "local"),
    ("M0037", "함숫값", "f(2)를 2f로 계산", "대입 오류", "순서오류", "[9수02-14]", "local"),
    ("M0409", "하나의 x에 여러 y 가능", None, None, None, "[9수02-14]", None),
    (
        "M0567",
        "하나의 x에 y가 여럿 대응해도 함수로 본다. y가 변하지 않는 상수함수를 함수가 아니라고 본다.",
        None,
        None,
        None,
        "[9수02-14]",
        None,
    ),
    (
        "M0568",
        "기울기 a와 y절편 b의 역할을 바꾼다. 기울기를 Δx/Δy로 뒤집어 계산한다.",
        None,
        None,
        None,
        "[9수02-15]",
        None,
    ),
    (
        "M0569",
        "기울기의 부호와 그래프의 증가·감소를 반대로 본다",
        "기울기의 부호와 그래프의 증가·감소를 반대로 본다. 기울기가 0인 가로선을 빠뜨린다.",
        "정답 대신, 학생이 '기울기의 부호와 그래프의 증가·감소를 반대로 본다'처럼 잘못 처리한 결과를 오답 보기로 배치",
        "부호오류",
        "[9수02-16]",
        "cosmetic",
    ),
    (
        "M0001",
        "음수 곱셈",
        "(-)×(-)=(-) 라고 생각",
        "(-3)×(-4) 정답 12에 -12 배치",
        "부호오류",
        "[9수01-03]",
        "cosmetic",
    ),
    (
        "M0002",
        "음수 뺄셈",
        "3-(-5)=3-5=-2",
        "정답 8에 -2 배치",
        "부호오류",
        "[9수01-03]",
        "cosmetic",
    ),
)

_KEYS = (
    "mis_id",
    "canonical_statement",
    "student_wrong_thinking",
    "distractor_rule",
    "error_type",
    "standard_code",
    "severity",
)


class _CaptureStore:
    """옛 로더의 `store` 자리에 넣는 가짜 저장소 — DB에 쓰지 않고 받은 행만 모아 둔다."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def populate(
        self,
        misconceptions: list[Any],
        *,
        overwrite_cms_edits: bool = False,
        conflicts: list[str] | None = None,
    ) -> int:
        """옛 `MisconceptionCatalogStore.populate`와 같은 모양으로 받아 개수를 돌려준다."""
        del overwrite_cms_edits, conflicts
        self.received = list(misconceptions)
        return len(self.received)


def _corpus_rows(ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """코퍼스에서 주어진 ID의 행만 그 순서대로 고른다(나머지 행은 쓰지 않는다)."""
    rows = json.loads(CORPUS.read_text(encoding="utf-8"))["misconceptions"]
    by_id = {row["mis_id"]: row for row in rows}
    return [by_id[mis_id] for mis_id in ids]


def _call_old_loader(ids: tuple[str, ...]) -> tuple[int, list[tuple[str | None, ...]]]:
    """옛 함수를 옛 자리에서 부른다 → (반환 행 수, 저장소가 받은 행의 핵심 칸 7개)."""
    store = _CaptureStore()
    count = catalog_loader.load_misconceptions(
        None, {"misconceptions": _corpus_rows(ids)}, store=store  # type: ignore[arg-type]
    )
    dumped = [item.model_dump() for item in store.received]
    return count, [tuple(row[key] for key in _KEYS) for row in dumped]


def test_old_loader_is_called_from_its_old_place() -> None:
    """복사본이 아니라 옛 모듈 그 자체를 부른다(특성화 대상 확인)."""
    assert catalog_loader.__name__ == "whymath_backend.l1.misconception.catalog_loader"
    assert catalog_loader.load_misconceptions.__module__ == catalog_loader.__name__


def test_ten_ids_give_the_fixed_ten_outputs() -> None:
    """입력 ID 10개 → 반환 10 · 저장소가 받은 행 10개가 고정값과 같다(순서 포함)."""
    count, outputs = _call_old_loader(INPUT_IDS)
    assert count == 10
    assert tuple(outputs) == EXPECTED


def test_old_loader_is_deterministic_100_times() -> None:
    """같은 입력 100회 → 같은 출력(비결정적이면 다섯 걸음 규칙상 가져오지 않는다)."""
    first = _call_old_loader(INPUT_IDS)
    assert all(_call_old_loader(INPUT_IDS) == first for _ in range(100))


def test_golden_file_matches_old_loader_text_for_all_rows() -> None:
    """골든 자료 파일 11건의 글(서술·잘못된 생각·오답 규칙·성취기준)이 옛 로더 출력과 같다.

    골든 파일의 `statement`는 코퍼스의 `canonical_statement`다(칸 이름만 짧게 바꿈).
    주입기가 읽는 ID 순서도 파일 순서와 같아야 한다(`errors.ALL_MISCONCEPTIONS`).
    """
    golden = json.loads(GOLDEN_LF.read_text(encoding="utf-8"))
    rows = golden["misconceptions"]
    ids = tuple(row["mis_id"] for row in rows)
    assert golden["count"] == len(rows) == 11
    assert ids == errors.ALL_MISCONCEPTIONS
    _, outputs = _call_old_loader(ids)
    old_by_id = {out[0]: dict(zip(_KEYS, out, strict=True)) for out in outputs}
    for row in rows:
        old = old_by_id[row["mis_id"]]
        assert row["statement"] == old["canonical_statement"], row["mis_id"]
        assert row["student_wrong_thinking"] == old["student_wrong_thinking"], row["mis_id"]
        assert row["distractor_rule"] == old["distractor_rule"], row["mis_id"]
        assert row["standard_code"] == old["standard_code"], row["mis_id"]
