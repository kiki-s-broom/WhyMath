"""오개념 코퍼스 추출 CLI — `whymath-misconception`.

7계층 본문 JSON → 정규화 오개념(업로드 원천 기준 839행) **Collection JSON** +
`_provenance.json`(원본 sha256·집계). `whymath-ncic extract`(성취기준 코퍼스) 선례와 동형이다 —
추출은 `extract_misconceptions`(순수)가 담당하고 본 CLI는 경로 결선·직렬화·보고만 한다. 원본 JSON은
커밋하지 않고 산출물이 진실 원천이다.

사용(단일 명령 앱 — 서브명령명 불요):
    whymath-misconception --json <7계층.json> --output-dir data/corpus/misconceptions_v1
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from data_pipeline.misconception.extract import extract_misconceptions, load_json

app = typer.Typer(
    name="whymath-misconception",
    help="오개념 카탈로그 추출 (7계층 본문 JSON → 정규화 코퍼스). 와이매스 자체 저작.",
    rich_markup_mode=None,
    no_args_is_help=False,
    add_completion=False,
)

_SOURCE_CITATION = "출처: WhyMath 7계층 본문 코퍼스(자체 저작 — 교수학 오개념 분석)."
_LICENSE_NOTICE = (
    "와이매스 자체 저작물(오개념 서술·distractor 규칙·교정포인트). "
    "성취기준·CCSS 코드는 구조 메타(공공·사실)."
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def extract(
    json_path: Annotated[
        Path,
        typer.Option("--json", help="7계층 본문 JSON(개념 배열) 경로."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="코퍼스 산출물 저장 디렉토리."),
    ] = Path("data/corpus/misconceptions_v1"),
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="DEBUG 로그."),
    ] = False,
) -> None:
    """7계층 JSON에서 오개념을 추출·정규화해 Collection JSON + provenance로 저장."""
    _setup_logging(verbose)

    if not json_path.is_file():
        typer.echo(f"[!] JSON 파일 없음: {json_path}", err=True)
        raise typer.Exit(code=2)

    concepts = load_json(json_path)
    records, duplicates = extract_misconceptions(concepts)
    if not records:
        typer.echo("[!] 추출된 오개념이 0건입니다(L5_META.오개념 구조 확인).", err=True)
        raise typer.Exit(code=2)

    output_dir.mkdir(parents=True, exist_ok=True)
    collection = {
        "source_citation": _SOURCE_CITATION,
        "license_notice": _LICENSE_NOTICE,
        "collected_at": datetime.now(tz=timezone.utc).isoformat(),
        "count": len(records),
        "misconceptions": records,
    }
    misc_path = output_dir / "misconceptions.json"
    misc_path.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with_ccss = sum(1 for r in records if r["ccss_code"] is not None)
    with_error_type = sum(1 for r in records if r["error_type"] is not None)
    error_types = sorted({r["error_type"] for r in records if r["error_type"] is not None})
    digest = hashlib.sha256(json_path.read_bytes()).hexdigest()
    provenance = {
        "source_sha256": digest,
        "source_name": json_path.name,
        "uploaded": datetime.now(tz=timezone.utc).date().isoformat(),
        "counts": {
            "misconceptions": len(records),
            "duplicates_skipped": duplicates,
            "with_ccss": with_ccss,
            "with_error_type": with_error_type,
        },
        "error_types": error_types,
        "source_citation": _SOURCE_CITATION,
        "license_notice": _LICENSE_NOTICE,
        "post_extraction": [
            "L5_META.오개념 평탄화·한글 소스 키→안정 영문 키(데이터카드 §2).",
            "mis_id 유일(첫 등장 우선 dedup)·개념/성취기준 코드는 원천 보존(해소는 백엔드 로더).",
        ],
    }
    (output_dir / "_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    typer.echo(
        f"[OK] 오개념 {len(records)}건 저장 → {output_dir} "
        f"(중복 skip {duplicates}·CCSS {with_ccss}·error_type {with_error_type}·"
        f"sha256 {digest[:12]}…)."
    )


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    app()
