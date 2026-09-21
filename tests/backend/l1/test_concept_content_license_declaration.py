"""`concept_content_v1`의 라이선스 선언 ↔ 실제 데이터 정합 동결 — 저작권 레일의 집행 지점.

이 코퍼스는 2026-09-06까지 사이드카에 **"K-12 성취기준 본문은 NCIC 저작물이라 미수록"**이라고
선언해 두고, 실제로는 `explanation` 133건이 NCIC 성취기준 본문과 사실상 동일했다(그중 124건은
표기 정규화 후 글자 그대로 일치). 법적 위험은 없다 — NCIC 성취기준은 교육부 고시 제2022-33호라
저작권법 제7조 제1호(고시·공고·훈령)상 보호받지 못하는 저작물이고 NCIC 공개분은 공공누리
제1유형이며, 같은 본문을 `standards_v1`이 같은 근거로 895건 보유한다. 문제는 **선언이 데이터를
설명하지 못한다는 것** 자체였다. 선언이 거짓이면 그 선언에 기대는 하위 판단(감사 신호·리뷰
프롬프트·데이터 카드)이 전부 조용히 틀린다.

그래서 정정 방향은 데이터 삭제가 아니라 선언 정정이었고(Kiki 판단, 2026-09-06), 이 테스트가 그
정정의 **집행 지점**이다 — "정본화를 집행으로 착각한 완료 선언 금지"(CLAUDE.md). 산문 선언만
고치면 다음 재생성에서 같은 드리프트가 소리 없이 돌아온다.

검증 축과 그 **변별력 방향**(성공·실패 양쪽에서 다른 값을 내는지):
① 실측 ↔ 사이드카 `ncic_statement_overlap` 숫자 일치 — 데이터가 바뀌면(코퍼스 재생성·재서술)
   숫자가 어긋나 red. 정정 전 상태(선언 "미수록" + 데이터 133건)에서도 이 축이 red다.
② 겹침이 0이 아니면 두 선언(사이드카·본문 헤더)이 **NCIC 출처를 실제로 표시**해야 한다 —
   출처 표시를 지우면 red(공공누리 제1유형의 유일한 조건이 출처 표시다).
③ 거짓이 된 옛 선언 문구("본문 ... 미수록")가 되살아나면 red — 문자열 금지 목록이 아니라
   *지금 데이터로 거짓인 주장*만 좁혀 막는다(겹침이 0으로 내려가면 이 축은 자동 해제된다).
④ 두 파일의 선언이 서로 달라지면 red — 한쪽만 고치는 부분 정정을 막는다.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTENT = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "content.json"
_PROVENANCE = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "_provenance.json"
_STANDARDS = _REPO_ROOT / "data" / "corpus" / "standards_v1" / "standards.json"

# 표기 흔들림(띄어쓰기·가운뎃점·괄호·따옴표)을 걷어 낸 뒤 비교한다 — "이산확률 변수의" ↔
# "이산확률변수의"처럼 옮겨 적으며 생긴 차이를 다른 문장으로 세면 겹침을 과소평가한다.
_NORMALIZE_STRIP = re.compile(r"[\s·,.'\"()]")

# 옛 선언이 되살아났는지 보는 패턴 — "성취기준 본문 ... 미수록"이라는 *주장*만 좁혀 잡는다.
# (금지 문자열 열거가 아니라 데이터로 거짓인 명제를 잡는 것이다 — CLAUDE.md "산출물 검사".)
_FALSE_ABSENCE_CLAIM = re.compile(r"성취기준 본문[^.]{0,40}미수록")


def _normalize(text: str | None) -> str:
    return _NORMALIZE_STRIP.sub("", text or "")


def _best_ratio(explanation: str, statements: list[str]) -> float:
    return max(
        (
            difflib.SequenceMatcher(None, _normalize(explanation), _normalize(s)).ratio()
            for s in statements
            if s
        ),
        default=0.0,
    )


@pytest.fixture(scope="module")
def declarations() -> tuple[dict, dict]:
    return (
        json.loads(_CONTENT.read_text(encoding="utf-8")),
        json.loads(_PROVENANCE.read_text(encoding="utf-8")),
    )


@pytest.fixture(scope="module")
def measured(declarations: tuple[dict, dict]) -> tuple[int, int]:
    """실 코퍼스 전수 스캔 — (겹침 건수, 정규화 후 완전 일치 건수)."""
    content, _ = declarations
    standards = json.loads(_STANDARDS.read_text(encoding="utf-8"))["standards"]
    by_code = {s["code"]: (s.get("statement") or "") for s in standards}

    threshold = json.loads(_PROVENANCE.read_text(encoding="utf-8"))["ncic_statement_overlap"][
        "similarity_threshold"
    ]
    overlap = exact = 0
    for record in content["content"]:
        explanation = record.get("explanation") or ""
        if not explanation:
            continue
        linked = [by_code[c] for c in (record.get("standard_codes") or []) if by_code.get(c)]
        if not linked:
            continue
        if _best_ratio(explanation, linked) < threshold:
            continue
        overlap += 1
        if any(_normalize(explanation) == _normalize(s) for s in linked):
            exact += 1
    return overlap, exact


def test_overlap_matches_sidecar(declarations, measured) -> None:
    """① 실측 ↔ 사이드카 숫자 — 코퍼스가 바뀌면 사이드카도 함께 갱신해야 한다."""
    _, provenance = declarations
    declared = provenance["ncic_statement_overlap"]
    assert (declared["count"], declared["exact_after_normalization"]) == measured, (
        f"NCIC 성취기준 본문 겹침 실측 {measured} ≠ 사이드카 선언 "
        f"({declared['count']}, {declared['exact_after_normalization']}). "
        "explanation을 재서술·재생성했다면 _provenance.json의 ncic_statement_overlap과 "
        "license_notice의 건수를 함께 갱신하라 — 선언은 데이터를 설명해야 한다."
    )


def test_attribution_present_when_overlap_exists(declarations, measured) -> None:
    """② 겹침이 있으면 두 선언 모두 NCIC 출처를 실제로 표시한다(공공누리 제1유형의 조건)."""
    content, provenance = declarations
    overlap, _ = measured
    if overlap == 0:
        pytest.skip("겹침 0건 — 출처 표시 의무가 발생하지 않는다")

    for label, doc in (("content.json", content), ("_provenance.json", provenance)):
        blob = f"{doc['source_citation']}\n{doc['license_notice']}"
        for marker in ("NCIC", "교육부 고시 제2022-33호", "공공누리"):
            assert marker in blob, (
                f"{label}의 출처 표시에 '{marker}'가 없다 — explanation {overlap}건이 NCIC "
                "성취기준 본문인데 출처 표시가 빠지면 공공누리 제1유형의 유일한 조건이 깨진다."
            )


def test_false_absence_claim_absent(declarations, measured) -> None:
    """③ 데이터로 거짓이 된 옛 주장("성취기준 본문 미수록")이 되살아나면 red."""
    content, provenance = declarations
    overlap, _ = measured
    if overlap == 0:
        pytest.skip("겹침 0건 — '미수록' 주장이 참이 되므로 이 축은 해제된다")

    for label, doc in (("content.json", content), ("_provenance.json", provenance)):
        for field in ("source_citation", "license_notice"):
            assert not _FALSE_ABSENCE_CLAIM.search(doc[field]), (
                f"{label}의 {field}가 '성취기준 본문 미수록'을 주장하는데 실측 겹침은 {overlap}건이다 "
                "— 선언이 데이터와 모순된다(2026-09-06 정정분 회귀)."
            )


def test_two_declarations_agree(declarations) -> None:
    """④ 본문 헤더와 사이드카의 선언이 서로 어긋나면 red — 부분 정정 방지."""
    content, provenance = declarations
    for field in ("source_citation", "license_notice"):
        assert content[field] == provenance[field], (
            f"content.json과 _provenance.json의 {field}가 다르다 — 한쪽만 고치면 "
            "어느 쪽이 정본인지 결정 불가가 된다."
        )
