"""개념 콘텐츠 코퍼스 감사 CLI — `review_status` 축 + 결함율 리포트(순수·결정론·LLM 0·DB 0).

정본: `docs/standards/superhuman_verification_standard.md` §2 S5(보증된 오류 상한). 이 감사가
드러내려는 사실은 하나다 — **`data/corpus/concept_content_v1`의 437행은 전량 'AI 추정·검수필요'
(`_provenance.json`)인데 이미 학생에게 렌더되어 나가고 있다.** 그 상태를 산문이 아니라 숫자로
남기지 않으면 "검수됐다고 가정하고 쓰는" 조용한 승격이 일어난다.

`harness/corpus_audit_eval`(문항 합격 로트 샘플링 게이트)과의 차이:
  · corpus_audit_eval — *사람이 라벨링한 표본*을 받아 문항 코퍼스의 결함율 상한을 게이트한다.
  · 이 모듈 — *기계가 전수 스캔*해 개념 콘텐츠의 **구조적** 결함(필드 결측·연결 결측·렌더 투영
    거부)과 explanation의 **내용 오염**(NCIC 크롤링 잔류), **검수 상태**를 센다. 사람 라벨을
    대체하지 않는다(구조 결함과 잔류 표기는 기계가 전수로 볼 수 있지만, 내용의 교수학적
    타당성은 여전히 사람·상위 게이트 몫이다 — 검증 권위 서열 준수).

**축을 새로 만들지 않는다**: `review_status`는 `db/models/concept_content.py`가 이미 쓰는 축이며,
이 감사는 그 값을 코퍼스에서 읽어 셀 뿐이다. 결함 분류도 새 enum이 아니라 *결측된 필드 이름*을
그대로 키로 쓴다(집계 키 = 이미 있는 필드명).

결함율은 점추정이 아니라 **Wilson 95% 단측 상한**으로 본다 — "낮을수록 좋은" 비율이라 상한을
보는 것이 정직하다(`corpus_audit_eval` 동형·표본이 전수여도 상한>점추정).

사용:
    python -m whymath_backend.harness.concept_content_audit
    python -m whymath_backend.harness.concept_content_audit --json out/audit.json
    python -m whymath_backend.harness.concept_content_audit --max-defect-upper 0.05
    python -m whymath_backend.harness.concept_content_audit --max-unreviewed-rate 0.5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whymath_backend.harness.concept_assessment_index import (
    DEFAULT_CONCEPT_PATH,
    ConceptRow,
    load_concepts,
)
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.render.dsl import from_concept_content

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_INPUT_ERROR = 2

# 검수 상태 리터럴 — `db/models/concept_content.CONTENT_REVIEW_STATUS_AI_ESTIMATED`와 같은 값이다.
# 여기서 db를 런타임 import하지 않는 이유는 `problem_bank_coverage`와 같다(관측 도구가 영속
# 계층에 결합하면 안 된다). 값 일치는 거버넌스 테스트가 실제 상수를 import해 동결한다.
REVIEW_STATUS_AI_ESTIMATED = "ai_estimated"

# 검수 상태 미표기 행의 집계 키 — "미표기"와 "ai_estimated"를 섞지 않는다(모르면 모른다).
REVIEW_STATUS_MISSING = "(미표기)"

# 결함 신호 — 결측 신호는 *기존 필드 이름*을 그대로 키로 쓴다(새 분류축 신설 금지). 내용 오염
# 신호(아래 explanation_* 2종)만 `<필드>_<형태>`로 명명해 결측 키와 섞이지 않게 한다.
DEFECT_MISSING_FIELDS: tuple[str, ...] = (
    "metaphor",
    "misconception",
    "formal_definition_internal",
    "accepted_expressions",
)
DEFECT_NO_STANDARD_CODES = "standard_codes_empty"
"""연결 성취기준 코드가 없다 — 교육과정 다리 없이 학생에게 노출되는 개념."""

DEFECT_DSL_PROJECTION_REJECTED = "dsl_projection_rejected"
"""렌더 투영(`from_concept_content`)이 거부 — 교수법-중립 위반 등으로 학생에게 나갈 수 없다."""

DEFECT_EXPLANATION_REVISION_MARK = "explanation_revision_mark"
"""explanation에 'NNNN 개정' 꼴 개정 연도 표기 — NCIC 크롤링 잔류. 코퍼스 사이드카의
NCIC 페이지에서 긁어 온 흔적이며, 개념 gloss에 개정 연도가 등장할 정상 경로는 없다.
(2026-09-06까지 이 신호의 근거는 사이드카의 "성취기준 본문 미수록" 선언이었으나, 그 선언 자체가
데이터와 모순임이 실측돼 정정됐다 — 성취기준 본문의 *보유*는 이제 허용된다. 이 신호가 잡는 것은
보유가 아니라 **파손**이다: 문장 중간에 낀 서지 표기.)"""

DEFECT_EXPLANATION_SECTION_TRAILER = "explanation_section_trailer"
"""explanation에 '(N) 절제목' 꼴 페이지·절 표기 — 같은 NCIC 크롤링 잔류의 두 번째 형태."""

DEFECT_EXPLANATION_PAGE_INSERT = "explanation_page_insert"
"""explanation 문장 중간에 조사 직후 bare 페이지 숫자 삽입('방법을 70 설명할 수 있다' 꼴) —
크롤링 잔류의 세 번째 형태. 47건 정정(QUAL-06) 후 추가 발견된 1건(H:12대수03-05)에서 확인."""

# 잔류 탐지 패턴 — 오탐 방지를 위해 형태별로 분리한다. explanation은 개념 gloss라 개정 연도나
# 페이지·절 표기가 정상 등장할 경로가 없고, 수학 표기 속 괄호(예: "(a+b)^n", "(연쇄법칙)")는
# `\(\d+\)`가 걸러 낸다. PAGE_INSERT는 '조사(을/를)+숫자+한글'로 좁혀 "분모 10 진분수" 같은
# 정상 서술(조사 없음)을 오탐하지 않는다. 2026-08-13 실 코퍼스 전수 실측 근거: 정정 전 오염
# 47건을 앞 두 패턴의 합집합이 전부 탐지하고 나머지 390건에서는 오탐 0건이었다(QUAL-06).
# 이후 재오염은 이 신호가 전수 스캔으로 잡아 낸다.
_RESIDUE_REVISION_MARK = re.compile(r"\d{4}\s*개정")
_RESIDUE_SECTION_TRAILER = re.compile(r"\(\d+\)\s*[가-힣]")
_RESIDUE_PAGE_INSERT = re.compile(r"[을를]\s+\d{1,3}\s+[가-힣]")


@dataclass(frozen=True, slots=True)
class ConceptDefect:
    """결함 1건 — 어느 개념의 어떤 신호인지(사람이 바로 고칠 수 있는 최소 정보)."""

    code: str
    subject: str
    defect: str


@dataclass(slots=True)
class AuditReport:
    """감사 결과 — 검수 상태 분포 + 결함율(점추정·Wilson 상한) + 결함 상세."""

    total: int
    review_status_counts: dict[str, int]
    defects: list[ConceptDefect]
    defect_counts: dict[str, int]
    defective_concepts: int

    @property
    def unreviewed(self) -> int:
        """검수 완료가 아닌 행 수 — 'reviewed'가 아닌 모든 상태(미표기 포함)."""
        return sum(
            count for status, count in self.review_status_counts.items() if status != "reviewed"
        )

    @property
    def unreviewed_rate(self) -> float | None:
        """미검수 비율(점추정). 행 0이면 None(미상을 0%로 위장하지 않는다)."""
        if self.total == 0:
            return None
        return self.unreviewed / self.total

    @property
    def defect_rate(self) -> float | None:
        """결함 개념 비율(점추정). 행 0이면 None."""
        if self.total == 0:
            return None
        return self.defective_concepts / self.total

    def defect_rate_upper(self, confidence: float = 0.95) -> float | None:
        """결함율 Wilson 단측 상한 — '표본에서 적게 나왔다'를 '코퍼스가 깨끗하다'로 읽지 않는다."""
        if self.total == 0:
            return None
        return wilson_upper_bound(self.defective_concepts, self.total, confidence)

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "review_status_counts": dict(sorted(self.review_status_counts.items())),
            "unreviewed": self.unreviewed,
            "unreviewed_rate": self.unreviewed_rate,
            "defective_concepts": self.defective_concepts,
            "defect_rate": self.defect_rate,
            "defect_rate_upper": self.defect_rate_upper(),
            "defect_counts": dict(sorted(self.defect_counts.items())),
            "defects": [
                {"code": d.code, "subject": d.subject, "defect": d.defect} for d in self.defects
            ],
        }


def audit_concepts(rows: list[ConceptRow]) -> AuditReport:
    """개념 행 전수 감사 → 리포트(순수·결정론).

    한 개념이 여러 결함을 가질 수 있으므로 결함 *건수*와 결함 *개념 수*를 나눠 센다 — 결함율의
    분자는 개념 수다(같은 개념을 여러 번 세면 비율이 1을 넘는다).
    """
    status_counts: Counter[str] = Counter()
    defect_counts: Counter[str] = Counter()
    defects: list[ConceptDefect] = []
    defective: set[str] = set()

    for row in rows:
        status_counts[row.review_status or REVIEW_STATUS_MISSING] += 1

        found: list[str] = []
        for field_name in DEFECT_MISSING_FIELDS:
            if getattr(row, field_name) is None:
                found.append(f"missing:{field_name}")
        if not row.standard_codes:
            found.append(DEFECT_NO_STANDARD_CODES)
        if row.explanation is not None:
            # 크롤링 잔류는 결측이 아니라 *내용 오염* — 값이 있을 때만 스캔한다(None을 정상으로
            # 봐야 하는 이유가 아니라, 결측 결함은 위의 missing 축 소관이라 중복 집계하지 않는다).
            if _RESIDUE_REVISION_MARK.search(row.explanation):
                found.append(DEFECT_EXPLANATION_REVISION_MARK)
            if _RESIDUE_SECTION_TRAILER.search(row.explanation):
                found.append(DEFECT_EXPLANATION_SECTION_TRAILER)
            if _RESIDUE_PAGE_INSERT.search(row.explanation):
                found.append(DEFECT_EXPLANATION_PAGE_INSERT)
        try:
            from_concept_content(row)
        except ValueError:
            # pydantic ValidationError는 ValueError 하위 — 중립성 위반·필수 필드 결측.
            found.append(DEFECT_DSL_PROJECTION_REJECTED)

        for defect in found:
            defect_counts[defect] += 1
            defects.append(ConceptDefect(code=row.code, subject=row.subject, defect=defect))
            defective.add(row.code)

    defects.sort(key=lambda d: (d.code, d.defect))
    return AuditReport(
        total=len(rows),
        review_status_counts=dict(status_counts),
        defects=defects,
        defect_counts=dict(defect_counts),
        defective_concepts=len(defective),
    )


def _fmt_rate(value: float | None) -> str:
    """비율 표기 — None은 "미상"(0%로 위장하지 않는다)."""
    return "미상" if value is None else f"{value * 100:.1f}%"


def render_report(report: AuditReport, *, max_listed: int = 20) -> str:
    """사람 가독 감사 리포트."""
    lines = [
        "=" * 72,
        "개념 콘텐츠 코퍼스 감사 — 검수 상태 + 결함율 (전수·결정론)",
        "=" * 72,
        f"개념 {report.total}행",
        "[검수 상태 분포]",
    ]
    for status, count in sorted(report.review_status_counts.items()):
        lines.append(f"  {status}: {count}")
    lines.append(
        f"  → 미검수 {report.unreviewed}행 ({_fmt_rate(report.unreviewed_rate)}) — "
        "이 상태로 학생 렌더 경로에 노출 중"
    )
    lines.append("[결함]")
    lines.append(
        f"  결함 개념 {report.defective_concepts}  결함율 {_fmt_rate(report.defect_rate)}  "
        f"Wilson 상한 {_fmt_rate(report.defect_rate_upper())}"
    )
    if report.defect_counts:
        for defect, count in sorted(report.defect_counts.items()):
            lines.append(f"  {defect}: {count}")
    else:
        lines.append("  (구조적 결함 신호 0 — 내용 타당성은 이 감사의 범위 밖)")
    if report.defects:
        lines.append("[결함 상세]")
        for detail in report.defects[:max_listed]:
            lines.append(f"  {detail.code} ({detail.subject}): {detail.defect}")
        if len(report.defects) > max_listed:
            lines.append(f"  … 외 {len(report.defects) - max_listed}건")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI — 개념 콘텐츠 코퍼스 전수 감사(리포트 기본·임계 지정 시 게이트)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.concept_content_audit",
        description=(
            "개념 콘텐츠 코퍼스의 검수 상태(review_status)와 구조적 결함율을 전수 감사한다."
        ),
    )
    parser.add_argument(
        "--concepts", type=Path, default=DEFAULT_CONCEPT_PATH, help="개념 콘텐츠 content.json 경로."
    )
    parser.add_argument("--json", type=Path, default=None, help="리포트 JSON 저장 경로.")
    parser.add_argument(
        "--max-defect-upper",
        type=float,
        default=None,
        help="결함율 Wilson 상한 임계(옵트인 게이트 — 초과 시 exit 1).",
    )
    parser.add_argument(
        "--max-unreviewed-rate",
        type=float,
        default=None,
        help="미검수 비율 임계(옵트인 게이트 — 초과 시 exit 1).",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_concepts(args.concepts)
    except (OSError, ValueError) as exc:
        print(
            f"입력 오류 — error_type={type(exc).__name__} concepts={args.concepts}",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR

    report = audit_concepts(rows)
    print(render_report(report))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"리포트 JSON: {args.json}")

    exit_code = _EXIT_OK
    upper = report.defect_rate_upper()
    if args.max_defect_upper is not None and (upper is None or upper > args.max_defect_upper):
        print(
            f"게이트 실패 — 결함율 상한 {_fmt_rate(upper)} > {_fmt_rate(args.max_defect_upper)}",
            file=sys.stderr,
        )
        exit_code = _EXIT_GATE_FAIL
    rate = report.unreviewed_rate
    if args.max_unreviewed_rate is not None and (rate is None or rate > args.max_unreviewed_rate):
        print(
            f"게이트 실패 — 미검수 비율 {_fmt_rate(rate)} > {_fmt_rate(args.max_unreviewed_rate)}",
            file=sys.stderr,
        )
        exit_code = _EXIT_GATE_FAIL
    return exit_code


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())


__all__ = [
    "DEFECT_DSL_PROJECTION_REJECTED",
    "DEFECT_EXPLANATION_PAGE_INSERT",
    "DEFECT_EXPLANATION_REVISION_MARK",
    "DEFECT_EXPLANATION_SECTION_TRAILER",
    "DEFECT_MISSING_FIELDS",
    "DEFECT_NO_STANDARD_CODES",
    "REVIEW_STATUS_AI_ESTIMATED",
    "REVIEW_STATUS_MISSING",
    "AuditReport",
    "ConceptDefect",
    "audit_concepts",
    "main",
    "render_report",
]
