"""K-12 개념 콘텐츠 코퍼스 빌드 CLI — xlsx → content.json + _provenance.json.

`concept_content_university/__main__.py` 미러. extract(개념+암기카드 조인) → validate → write
(자체작성 표지 + provenance sha256). 원본 xlsx 미커밋(휘발 → sha256 재현성). 연결 성취기준
코드 보존. 콘텐츠 DB 투영은 Phase 3.

라이선스 선언은 상수가 아니라 **빌드 시점 실측으로 합성**한다(`ncic_overlap`) — `explanation`과
연결 성취기준 본문의 겹침을 전수 비교해 그 건수로 `source_citation`·`license_notice`를 만들고,
기계 판독용 `ncic_statement_overlap`을 사이드카에 함께 남긴다. 숫자를 박아 두면 다른 xlsx로
재생성했을 때 사실과 다른 라이선스 표기가 나간다(PR #998 리뷰 지적).

사용:
    python -m data_pipeline.concept_content \
        --input /path/master.xlsx \
        --output-dir data/corpus/concept_content_v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from data_pipeline.concept_content.extract import extract_k12_content
from data_pipeline.concept_content.models import ConceptContent
from data_pipeline.concept_content.ncic_overlap import (
    DEFAULT_STANDARDS_PATH,
    OverlapReport,
    build_license_notice,
    build_source_citation,
    load_standard_statements,
    measure_overlap,
)
from data_pipeline.concept_content.validate import validate_content

_CRAWLER_VERSION = "0.1.0"
_DEFAULT_OUTPUT_DIR = Path("data/corpus/concept_content_v1")
_SOURCE_NAME = "54c14913-260622__________________.xlsx"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _collection(items: list[ConceptContent], overlap: OverlapReport) -> dict[str, object]:
    return {
        "source_citation": build_source_citation(overlap),
        "license_notice": build_license_notice(overlap),
        "scope": "K-12",
        "collected_at": _now(),
        "crawler_version": _CRAWLER_VERSION,
        "content": [c.model_dump(mode="json") for c in items],
    }


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _merge_sidecar(path: Path, payload: dict[str, object]) -> dict[str, object]:
    """기존 사이드카의 *우리가 쓰지 않는* 키를 보존한 채 갱신분을 얹는다.

    통째 덮어쓰기는 `pool`(ContentPool 분류·`provenance_audit`이 요구)처럼 다른 도구가
    넣어 둔 키를 조용히 지운다. 재생성이 사이드카를 *퇴화*시키면 안 된다 — PB-11 사이드카
    CLI의 비파괴 계약과 같은 취지다.
    """
    if not path.exists():
        return payload
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 침묵 실패 금지 — 예외 타입명을 남기고 신규 생성으로 진행한다.
        print(f"기존 사이드카를 읽지 못해 새로 씁니다({type(exc).__name__}): {path}")
        return payload
    if not isinstance(existing, dict):
        return payload
    merged = dict(existing)
    merged.update(payload)
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="concept-content-build",
        description=(
            "통합마스터 xlsx → K-12 개념 콘텐츠 코퍼스" "(자체작성·검수필요·NCIC 겹침 실측 표기)"
        ),
    )
    parser.add_argument("--input", type=Path, required=True, help="통합마스터 xlsx 경로")
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--standards",
        type=Path,
        default=DEFAULT_STANDARDS_PATH,
        help="NCIC 성취기준 코퍼스 — explanation 겹침 실측의 대조군(라이선스 선언 근거)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"입력 xlsx 없음: {args.input}")
        return 2

    if not args.standards.exists():
        # 측정 없이 선언을 쓰지 않는다 — 겹침을 모르는 채 쓴 라이선스 표기는 사실이 아닐 수
        # 있고, 그 거짓은 무증상으로 서빙 경로까지 간다(2026-09-06 실사에서 실제로 일어났다).
        print(f"성취기준 코퍼스 없음: {args.standards} — 겹침 실측 불가로 중단합니다.")
        return 2

    items = extract_k12_content(args.input)
    report = validate_content(items)
    print(report.summary())
    if not report.is_valid:
        print("검증 실패(error 존재) — 코퍼스를 쓰지 않습니다.")
        return 1

    overlap = measure_overlap(
        [(c.explanation or "", c.standard_codes) for c in items],
        load_standard_statements(args.standards),
    )
    print(
        f"NCIC 성취기준 본문 겹침: {overlap.count}건"
        f"(완전 일치 {overlap.exact} · 비교 대상 {overlap.total_with_explanation} · "
        f"임계 {overlap.threshold})"
    )

    out: Path = args.output_dir
    _write_json(out / "content.json", _collection(items, overlap))
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    sidecar_path = out / "_provenance.json"
    _write_json(
        sidecar_path,
        _merge_sidecar(
            sidecar_path,
            {
                "source_sha256": digest,
                "source_name": _SOURCE_NAME,
                "uploaded": datetime.now(tz=timezone.utc).date().isoformat(),
                "counts": {
                    "content": len(items),
                    "flashcards": report.flashcard_count,
                    "subjects": report.subject_count,
                },
                "source_citation": build_source_citation(overlap),
                "license_notice": build_license_notice(overlap),
                "ncic_statement_overlap": overlap.as_sidecar(
                    measured_at=datetime.now(tz=timezone.utc).date().isoformat()
                ),
                "post_extraction": [
                    "개념(학교급!='대학교') 437 + 암기카드 조인 추출. 대학 비추출(U4 별도).",
                    "explanation 일부는 NCIC 성취기준 본문과 동일(교육부 고시 §7 비보호·공공누리 "
                    "제1유형·출처 표시). 연결 성취기준 코드 보존. 정식정의=학생 비노출. "
                    "DB 투영 Phase 3.",
                ],
            },
        ),
    )
    print(
        f"K-12 콘텐츠 코퍼스 작성: {out} (content={len(items)}·"
        f"flashcards={report.flashcard_count}·subjects={report.subject_count}·sha256={digest[:12]}…)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
