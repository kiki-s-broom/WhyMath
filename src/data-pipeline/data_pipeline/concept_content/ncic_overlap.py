"""`explanation` ↔ NCIC 성취기준 본문 겹침 측정 + 그 실측치로 라이선스 선언을 합성한다.

**왜 측정을 생성 경로에 두는가.** 2026-09-06 실사에서 K-12 콘텐츠 코퍼스의 `explanation` 133건이
NCIC 성취기준 본문과 사실상 동일함이 드러났는데, 사이드카는 "성취기준 본문 미수록"을 선언하고
있었다. 그 정정을 커밋된 코퍼스 파일에만 하면 다음 재생성에서 옛 선언이 소리 없이 돌아온다 —
그래서 선언 문자열을 **여기서 측정한 숫자로 합성**한다. 숫자를 상수로 박아 두면 다른 xlsx로
재생성했을 때 사실과 다른 라이선스 표기가 나간다(PR #998 리뷰 지적).

**법적 배경**(선언 문구의 근거): NCIC 성취기준은 교육부 고시 제2022-33호라 저작권법 제7조 제1호
(고시·공고·훈령)상 보호받지 못하는 저작물이고, NCIC 공개분은 공공누리 제1유형(출처 표시·상업
이용·변경 허용)이다. 같은 본문을 `standards_v1`이 같은 근거로 895건 보유한다. 따라서 겹침은
*제거 대상이 아니라 표기 대상*이며, 공공누리 제1유형의 유일한 조건인 **출처 표시**를 선언이
반드시 담아야 한다. 반면 NCIC *해설서·연구보고서*는 영리 차단(C등급)이라 성격이 다르다 —
`docs/data/licensing_safety.md`의 'NCIC 구분'.

집행: `tests/backend/l1/test_concept_content_license_declaration.py`(커밋된 코퍼스 전수 스캔 ↔
사이드카 대조) · `tests/data_pipeline/concept_content/test_models_validate.py`(생성원 ↔ 산출물).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from data_pipeline.citation import build_ncic_citation_core

DEFAULT_STANDARDS_PATH: Final[Path] = Path("data/corpus/standards_v1/standards.json")

SIMILARITY_THRESHOLD: Final[float] = 0.90
"""이 값 이상이면 '사실상 동일'로 센다.

판단선이지 법적 경계가 아니다 — NCIC 본문은 어차피 §7 비보호라 임계를 어디에 두든 합법성은
같다. 이 숫자가 정하는 것은 *선언이 보고할 건수*이며, 사이드카에 함께 적어 두어 임계를 바꾸면
게이트가 숫자 불일치로 red를 내게 한다.
"""

_NORMALIZE_STRIP: Final[re.Pattern[str]] = re.compile(r"[\s·,.'\"()]")
"""표기 흔들림(띄어쓰기·가운뎃점·괄호·따옴표)만 걷어 낸다.

"이산확률 변수의" ↔ "이산확률변수의"처럼 옮겨 적으며 생긴 차이를 다른 문장으로 세면 겹침을
과소평가한다. 어미·조사는 건드리지 않는다 — 그건 표기 차이가 아니라 내용 차이다.
"""


def normalize(text: str | None) -> str:
    """비교용 정규화 — 표기 흔들림 제거."""
    return _NORMALIZE_STRIP.sub("", text or "")


@dataclass(frozen=True, slots=True)
class OverlapReport:
    """겹침 실측 결과 — 선언 합성과 사이드카 기록의 단일 근거."""

    count: int
    """유사도 ≥ `threshold`인 `explanation` 건수."""

    exact: int
    """그중 정규화 후 완전 일치한 건수(`count`의 부분집합)."""

    threshold: float
    total_with_explanation: int
    """`explanation`이 있고 연결 성취기준 본문을 찾을 수 있었던 레코드 수(분모)."""

    def as_sidecar(self, *, measured_at: str) -> dict[str, object]:
        """`_provenance.json`에 실을 기계 판독 형태.

        산문 선언은 사람이 읽고, 이 객체는 게이트가 읽는다 — 둘이 어긋나면 게이트가 red를 낸다.
        """
        return {
            "field": "explanation",
            "reference": "data/corpus/standards_v1/standards.json (교육부 고시 제2022-33호)",
            "similarity_threshold": self.threshold,
            "count": self.count,
            "exact_after_normalization": self.exact,
            "compared": self.total_with_explanation,
            "measured_at": measured_at,
            "legal_basis": (
                "저작권법 제7조 제1호(고시) 비보호 + 공공누리 제1유형(출처 표시) — "
                "보유·상업 이용 제약 없음"
            ),
            "enforced_by": "tests/backend/l1/test_concept_content_license_declaration.py",
        }


def load_standard_statements(path: str | Path = DEFAULT_STANDARDS_PATH) -> dict[str, str]:
    """`standards_v1` 코퍼스에서 `{성취기준 코드: 본문}`을 읽는다.

    Raises:
        FileNotFoundError: 코퍼스가 없으면 **측정 없이 진행하지 않는다**. 겹침을 모르는 채로
            선언을 쓰면 사실과 다른 라이선스 표기가 나가므로, 조용한 0건 폴백을 두지 않는다.
    """
    import json

    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    return {
        entry["code"]: (entry.get("statement") or "")
        for entry in raw["standards"]
        if entry.get("code")
    }


def _best_ratio(explanation: str, statements: list[str]) -> float:
    return max(
        (
            difflib.SequenceMatcher(None, normalize(explanation), normalize(s)).ratio()
            for s in statements
            if s
        ),
        default=0.0,
    )


def measure_overlap(
    records: list[tuple[str, list[str]]],
    statements_by_code: dict[str, str],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
) -> OverlapReport:
    """`(explanation, standard_codes)` 쌍들을 전수 비교한다.

    각 레코드는 **자기가 연결한 성취기준**하고만 비교한다(전체 895건과의 최근접 탐색이 아니다) —
    다른 단원의 우연한 유사 문장을 "본문 복제"로 세면 건수가 부풀고, 그 부풀린 숫자로 선언을
    쓰면 그것도 사실과 다르다.
    """
    count = exact = compared = 0
    for explanation, codes in records:
        if not explanation:
            continue
        linked = [statements_by_code[c] for c in codes if statements_by_code.get(c)]
        if not linked:
            continue
        compared += 1
        if _best_ratio(explanation, linked) < threshold:
            continue
        count += 1
        if any(normalize(explanation) == normalize(s) for s in linked):
            exact += 1
    return OverlapReport(
        count=count, exact=exact, threshold=threshold, total_with_explanation=compared
    )


def build_source_citation(report: OverlapReport) -> str:
    """코퍼스 헤더·사이드카의 `source_citation` — 실측 건수로 합성."""
    base = (
        "출처: 와이매스 자체작성 — K-12 개념 교수학 콘텐츠"
        "(은유·오개념·정식정의·허용표현·암기카드). 원자노드DB 종합·AI 추정·검수필요."
    )
    if report.count == 0:
        return f"{base} `explanation`은 전량 자체 서술이다(NCIC 성취기준 본문 겹침 0건·전수 실측)."
    return (
        f"{base} 단, `explanation` {report.count}건은 NCIC 성취기준 본문과 사실상 동일하며 "
        f"그 출처는 {build_ncic_citation_core()}다."
    )


def build_license_notice(report: OverlapReport) -> str:
    """코퍼스 헤더·사이드카의 `license_notice` — 실측 건수로 합성.

    겹침이 있으면 **출처 표시**(공공누리 제1유형의 유일한 조건)를 반드시 담고, 겹침이 0이면
    그 표시가 사실이 아니게 되므로 담지 않는다. 어느 쪽이든 선언이 데이터를 설명한다.
    """
    base = (
        "본 데이터(은유·오개념·정식정의·허용표현·설명·암기카드)는 와이매스 자체 저작물입니다 — "
        "AI 추정 초안으로 검수필요."
    )
    tail = "`formal_definition_internal`(정식정의)은 학생 비노출(내부·검수용)."
    if report.count == 0:
        return f"{base} `explanation`의 NCIC 성취기준 본문 겹침은 전수 실측 0건이다. {tail}"
    return (
        f"{base} **단, `explanation` {report.count}건은 NCIC 성취기준 본문과 사실상 동일하다"
        f"(유사도 ≥{report.threshold:.2f}·그중 {report.exact}건은 표기 정규화 후 완전 일치·"
        f"{report.total_with_explanation}건 중 전수 실측).** "
        f"해당 본문의 출처는 {build_ncic_citation_core()}이며, 고시는 저작권법 제7조 제1호"
        "(고시·공고·훈령)상 보호받지 못하는 저작물이고 NCIC 공개분은 공공누리 제1유형"
        "(출처 표시·상업 이용·변경 허용)이라 보유·상업 이용에 제약이 없다 — "
        "`licensing_safety.md`의 'NCIC 구분'(고시 본문 = §7 비보호 ↔ 해설서·연구보고서 = "
        "영리 차단)에서 전자에 해당한다. 나머지 explanation과 다른 5개 필드는 자체 저작물이다. "
        f"{tail}"
    )
