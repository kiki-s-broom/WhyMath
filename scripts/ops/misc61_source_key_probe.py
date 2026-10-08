"""MISC-61 ① 원천 대조 — 원천 JSON의 `distractor 연결됨` 88행·A3 4건이 어떤 키를 갖는지 읽는다.

**왜 필요한가**: 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`)에서
`provenance_note = "distractor 연결됨"`인 88행은 예외 없이 `student_wrong_thinking`·
`distractor_rule`·`error_type`이 비어 있다. 원인이 ①원천이 처음부터 비어 있음인지 ②추출기
(`extract.py`)가 고정 키만 읽어 다른 키의 값을 조용히 버렸는지는 **원천 JSON 없이 판정할 수
없고**, 그 파일은 저장소에 없다(Kiki 머신 보관본).

**이 스크립트가 하는 일**: 원천을 읽기 전용으로 열어 대상 행의 *키 이름과 비어 있지 않은
건수*만 센다. 행 본문(오개념 서술 등)은 출력하지 않는다 — 결과를 그대로 세션에 붙여넣어도
안전하다. DB·네트워크에 접속하지 않고, 쓰는 파일은 `--out`을 준 경우의 보고서 하나뿐이다.
표준 라이브러리만 쓴다(추가 설치 불요).

**출력 형태**: 표준 출력은 **ASCII 이스케이프 JSON**(`\\uXXXX`)이다 — 한국어 Windows 콘솔(cp949)·
PowerShell 중계에서 한글이 깨져 JSON 구조가 손상되는 것을 피한다. 읽기 좋은 UTF-8 본이 필요하면
`--out <경로>`를 준다.

**판정 규칙** (대상 = 코퍼스에서 세 필드가 모두 빈 `distractor 연결됨` 행 ∪ A3 4건):
  · 원천에서 세 필드 중 하나라도 비어 있지 않은 행이 있다 → `H2_known_key`
    (추출 이후 단계에서 빠졌다)
  · 세 필드는 비었지만 추출기가 모르는 키에 값이 있는 행이 있다 → `H2_unknown_key`
    (키 매핑 누락)
  · 어느 키에도 값이 없다 → `H1_source_empty` (원천부터 비었다)

종료 코드: 0 = 보고서 산출 · 2 = 입력 오류(파일 없음·형식 위반·대상 0건). **0은 판정이 났다는
뜻이 아니라 보고서를 냈다는 뜻**이다 — 판정은 보고서의 `verdict` 필드를 읽는다.

사용:
    python scripts/ops/misc61_source_key_probe.py --source <원천.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# 추출기(`data_pipeline/misconception/extract.py`)가 읽는 키 — 복제본이다. 어긋나면 `H2_unknown_key`
# 판정이 거짓이 되므로 `test_misc61_source_key_probe.py`가 추출기의 실제 매핑과 대조해 동결한다.
EXTRACTOR_KEYS = frozenset(
    {
        "mis_id",
        "오개념",
        "학생의_잘못된_사고",
        "distractor_규칙",
        "error_type",
        "난이도",
        "교정포인트",
        "매칭_CCSS",
        "개념ID",
        "성취기준코드",
        "학교급",
        "2022_영역",
        "세부단원_개념",
        "매핑신뢰도",
        "생성·검수",
        "매핑점수",
    }
)
# 코퍼스에서 비어 있던 세 필드의 원천 키
EMPTY_FIELD_SOURCE_KEYS = ("학생의_잘못된_사고", "distractor_규칙", "error_type")
A3_MIS_IDS = ("M0418", "M0599", "M0417", "M0600")
LINKED_NOTE = "distractor 연결됨"
PROVENANCE_NOTE_KEY = "생성·검수"

DEFAULT_CORPUS = Path("data/corpus/misconceptions_v1/misconceptions.json")
DEFAULT_PROVENANCE = Path("data/corpus/misconceptions_v1/_provenance.json")


def _nonempty(value: object) -> bool:
    """값이 있는가 — None·빈 문자열·공백·빈 리스트/매핑은 '없음'이다."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def flatten_source(concepts: object) -> list[dict[str, Any]]:
    """7계층 본문 JSON(개념 배열) → 오개념 행 목록. 추출기와 같은 경로(`L5_META.오개념`)를 탄다."""
    if not isinstance(concepts, list):
        raise ValueError(f"최상위가 개념 배열이어야 한다(got {type(concepts).__name__})")
    rows: list[dict[str, Any]] = []
    for concept in concepts:
        meta = concept.get("L5_META") if isinstance(concept, dict) else None
        for row in (meta or {}).get("오개념") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def corpus_empty_ids(corpus_path: Path) -> set[str]:
    """코퍼스에서 `distractor 연결됨`이면서 세 필드가 모두 빈 mis_id 집합."""
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for rec in payload.get("misconceptions", []):
        if rec.get("provenance_note") != LINKED_NOTE:
            continue
        if not any(
            _nonempty(rec.get(k))
            for k in ("student_wrong_thinking", "distractor_rule", "error_type")
        ):
            ids.add(str(rec.get("mis_id")))
    return ids


def probe(rows: list[dict[str, Any]], target_ids: set[str]) -> dict[str, Any]:
    """대상 행들의 키 구성을 센다. 행 본문은 보고서에 넣지 않는다."""
    targets = [r for r in rows if str(r.get("mis_id")) in target_ids]
    known_nonempty: Counter[str] = Counter()
    unknown_nonempty: Counter[str] = Counter()
    unknown_present: Counter[str] = Counter()
    rows_with_known_value = 0
    rows_with_unknown_value = 0
    for row in targets:
        has_known = any(_nonempty(row.get(k)) for k in EMPTY_FIELD_SOURCE_KEYS)
        for key in EMPTY_FIELD_SOURCE_KEYS:
            if _nonempty(row.get(key)):
                known_nonempty[key] += 1
        has_unknown = False
        for key, value in row.items():
            if key in EXTRACTOR_KEYS:
                continue
            unknown_present[key] += 1
            if _nonempty(value):
                unknown_nonempty[key] += 1
                has_unknown = True
        rows_with_known_value += int(has_known)
        rows_with_unknown_value += int(has_unknown)

    if not targets:
        verdict = "NO_TARGETS"
    elif rows_with_known_value:
        verdict = "H2_known_key"
    elif rows_with_unknown_value:
        verdict = "H2_unknown_key"
    else:
        verdict = "H1_source_empty"
    return {
        "verdict": verdict,
        "target_rows_found_in_source": len(targets),
        "rows_with_value_under_known_key": rows_with_known_value,
        "rows_with_value_under_unknown_key": rows_with_unknown_value,
        "known_key_nonempty_counts": dict(known_nonempty),
        "unknown_key_nonempty_counts": dict(unknown_nonempty),
        "unknown_key_present_counts": dict(unknown_present),
    }


def build_report(
    source_path: Path, corpus_path: Path, provenance_path: Path | None
) -> dict[str, Any]:
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = None
    if provenance_path is not None and provenance_path.is_file():
        expected = json.loads(provenance_path.read_text(encoding="utf-8")).get("source_sha256")
    rows = flatten_source(json.loads(raw.decode("utf-8")))
    linked = corpus_empty_ids(corpus_path)
    source_ids = {str(r.get("mis_id")) for r in rows}

    report: dict[str, Any] = {
        "source_name": source_path.name,
        "source_sha256": digest,
        "provenance_sha256": expected,
        # 다른 파일을 읽고 판정하면 H1/H2 모두 무의미하다 — 해시가 다르면 보고서 맨 앞에서 말한다.
        "sha256_matches_provenance": (digest == expected) if expected else None,
        "source_rows_total": len(rows),
        "corpus_distractor_linked_empty_rows": len(linked),
        "corpus_rows_missing_in_source": len(linked - source_ids),
        "extractor_known_keys": sorted(EXTRACTOR_KEYS),
        "all_targets": probe(rows, linked | set(A3_MIS_IDS)),
        "a3": {mid: probe(rows, {mid}) for mid in A3_MIS_IDS},
    }
    # 원천 행들이 가진 비표준 키 전체(대상 여부 무관) — 매핑 누락이 대상 밖에도 있는지 본다.
    all_unknown: Counter[str] = Counter()
    for row in rows:
        for key, value in row.items():
            if key not in EXTRACTOR_KEYS and _nonempty(value):
                all_unknown[key] += 1
    report["source_wide_unknown_key_nonempty_counts"] = dict(all_unknown)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="원천 7계층 본문 JSON 경로")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--out", type=Path, default=None, help="UTF-8 보고서 저장 경로(선택)")
    args = parser.parse_args(argv)

    for label, path in (("원천", args.source), ("코퍼스", args.corpus)):
        if not path.is_file():
            print(f"[!] {label} 파일 없음: {path}", file=sys.stderr)
            return 2
    try:
        report = build_report(args.source, args.corpus, args.provenance)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        # 예외 타입명을 남긴다 — 무타입 실패 금지
        print(f"[!] 입력 형식 오류({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    if args.out is not None:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    # 표준 출력은 ASCII 이스케이프 — 콘솔 인코딩이 무엇이든 JSON 구조 문자가 손상되지 않는다
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if report["all_targets"]["verdict"] == "NO_TARGETS":
        print("[!] 원천에서 대상 행을 하나도 찾지 못했다 — 다른 파일일 수 있다", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
