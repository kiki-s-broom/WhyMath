"""MISC-61 ① 원천 대조 — 원천 JSON의 `distractor 연결됨` 88행·A3 4건이 어떤 키를 갖는지 읽는다.

**왜 필요한가**: 코퍼스(`data/corpus/misconceptions_v1/misconceptions.json`)에서
`provenance_note = "distractor 연결됨"`인 88행은 예외 없이 `student_wrong_thinking`·
`distractor_rule`·`error_type`이 비어 있다. 원인이 ①원천이 처음부터 비어 있음인지 ②추출기
(`extract.py`)가 고정 키만 읽어 다른 키의 값을 조용히 버렸는지는 **원천 JSON 없이 판정할 수
없고**, 그 파일은 저장소에 없다(Kiki 머신 보관본).

**이 스크립트가 하는 일**: 원천을 읽기 전용으로 열어 대상 행의 *키 이름과 비어 있지 않은
건수*만 센다. 행 본문(오개념 서술 등)은 기본으로 출력하지 않는다 — 결과를 그대로 세션에 붙여넣어도
안전하다. 예외는 `--dump-key <키>`를 명시했을 때뿐이며, 그때도 *그 키 하나의 값*만 나온다(2차
실행: 값의 내용을 봐야 어느 필드로 보낼지 정할 수 있다). DB·네트워크에 접속하지 않고, 쓰는 파일은
`--out`을 준 경우의 보고서 하나뿐이다. 표준 라이브러리만 쓴다(추가 설치 불요).

**출력 형태**: 표준 출력은 **ASCII 이스케이프 JSON**(`\\uXXXX`)이다 — 한국어 Windows 콘솔(cp949)·
PowerShell 중계에서 한글이 깨져 JSON 구조가 손상되는 것을 피한다. 읽기 좋은 UTF-8 본이 필요하면
`--out <경로>`를 준다.

**판정 규칙** (대상 = 코퍼스에서 세 필드가 모두 빈 `distractor 연결됨` 행 ∪ A3 4건):
  · 원천에서 세 필드 중 하나라도 비어 있지 않은 행이 있다 → `H2_known_key`
    (추출 이후 단계에서 빠졌다)
  · 세 필드는 비었지만 추출기가 모르는 **내용 키**에 값이 있는 행이 있다 → `H2_unknown_key`
    (키 매핑 누락)
  · 어느 키에도 값이 없다 → `H1_source_empty` (원천부터 비었다)

**내용 키란** (2026-10-09 정정): 추출기가 모르는 키 가운데 **대상 밖 행의 90% 이상에 값이 있는 열
(공통 메타 열)은 뺀다.** 1차 실행에서 `출처`·`원본_영역` 등 원천 839행 전부에 있는 5열이 판정에
걸려 `H2_unknown_key`가 90/90으로 과장됐다. 대조군(대상 밖 행)이 `MIN_CONTROL_ROWS`보다 적으면
비율이 의미 없으므로 아무 열도 공통으로 보지 않는다(H2로 기우는 쪽이 보수적이다).

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

# 공통 메타 열 판정 — 대상 밖 행(대조군)에서 값이 있는 비율이 이 이상이면 내용 키가 아니다
UNIVERSAL_KEY_RATIO = 0.9
# 대조군이 이보다 적으면 비율이 의미 없다 → 공통 열을 인정하지 않는다(보수적)
MIN_CONTROL_ROWS = 20
ORIGINAL_NOTE = "원본"

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


def corpus_empty_ids(corpus_path: Path, note: str = LINKED_NOTE) -> set[str]:
    """코퍼스에서 `provenance_note == note`이면서 세 필드가 모두 빈 mis_id 집합(기본: 연결됨)."""
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for rec in payload.get("misconceptions", []):
        if rec.get("provenance_note") != note:
            continue
        if not any(
            _nonempty(rec.get(k))
            for k in ("student_wrong_thinking", "distractor_rule", "error_type")
        ):
            ids.add(str(rec.get("mis_id")))
    return ids


def universal_keys(rows: list[dict[str, Any]], target_ids: set[str]) -> frozenset[str]:
    """대상 밖 행(대조군)의 `UNIVERSAL_KEY_RATIO` 이상에 값이 있는 비표준 키 = 공통 메타 열.

    대조군이 `MIN_CONTROL_ROWS`보다 적으면 빈 집합 — 표본이 작을 때 모든 키가 '공통'으로 보이는
    것을 막는다.
    """
    controls = [r for r in rows if str(r.get("mis_id")) not in target_ids]
    if len(controls) < MIN_CONTROL_ROWS:
        return frozenset()
    counts: Counter[str] = Counter()
    for row in controls:
        for key, value in row.items():
            if key not in EXTRACTOR_KEYS and _nonempty(value):
                counts[key] += 1
    return frozenset(k for k, c in counts.items() if c / len(controls) >= UNIVERSAL_KEY_RATIO)


def probe(
    rows: list[dict[str, Any]],
    target_ids: set[str],
    universal: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """대상 행들의 키 구성을 센다. 행 본문은 보고서에 넣지 않는다.

    `universal`에 든 키(공통 메타 열)는 원시 집계(`unknown_key_*`)에는 남기되 판정에서는 뺀다.
    """
    targets = [r for r in rows if str(r.get("mis_id")) in target_ids]
    known_nonempty: Counter[str] = Counter()
    unknown_nonempty: Counter[str] = Counter()
    content_nonempty: Counter[str] = Counter()
    unknown_present: Counter[str] = Counter()
    rows_with_known_value = 0
    rows_with_unknown_value = 0
    rows_with_content_value = 0
    for row in targets:
        has_known = any(_nonempty(row.get(k)) for k in EMPTY_FIELD_SOURCE_KEYS)
        for key in EMPTY_FIELD_SOURCE_KEYS:
            if _nonempty(row.get(key)):
                known_nonempty[key] += 1
        has_unknown = False
        has_content = False
        for key, value in row.items():
            if key in EXTRACTOR_KEYS:
                continue
            unknown_present[key] += 1
            if _nonempty(value):
                unknown_nonempty[key] += 1
                has_unknown = True
                if key not in universal:
                    content_nonempty[key] += 1
                    has_content = True
        rows_with_known_value += int(has_known)
        rows_with_unknown_value += int(has_unknown)
        rows_with_content_value += int(has_content)

    if not targets:
        verdict = "NO_TARGETS"
    elif rows_with_known_value:
        verdict = "H2_known_key"
    elif rows_with_content_value:
        verdict = "H2_unknown_key"
    else:
        verdict = "H1_source_empty"
    return {
        "verdict": verdict,
        "target_rows_found_in_source": len(targets),
        "rows_with_value_under_known_key": rows_with_known_value,
        "rows_with_value_under_unknown_key": rows_with_unknown_value,
        "rows_with_value_under_content_key": rows_with_content_value,
        "known_key_nonempty_counts": dict(known_nonempty),
        "unknown_key_nonempty_counts": dict(unknown_nonempty),
        "content_unknown_key_nonempty_counts": dict(content_nonempty),
        "unknown_key_present_counts": dict(unknown_present),
    }


def dump_key_rows(rows: list[dict[str, Any]], key: str, corpus_path: Path) -> dict[str, Any]:
    """`key`에 값이 있는 원천 행의 (mis_id, 값)과, 코퍼스 '원본+세 필드 공란' 행과의 행 단위 일치.

    `--dump-key`를 명시했을 때만 호출된다 — 본문이 나오는 유일한 경로다. 같은 mis_id가 원천에
    두 번 나오면 첫 등장만 쓴다(추출기의 dedup과 같은 규칙).
    """
    seen: set[str] = set()
    values: list[dict[str, Any]] = []
    for row in rows:
        mid = str(row.get("mis_id"))
        if mid in seen or not _nonempty(row.get(key)):
            continue
        seen.add(mid)
        values.append({"mis_id": mid, "value": row.get(key)})
    corpus_ids = corpus_empty_ids(corpus_path, ORIGINAL_NOTE)
    source_ids = {v["mis_id"] for v in values}
    return {
        "key": key,
        "rows_with_value": len(values),
        "corpus_original_empty_rows": len(corpus_ids),
        "in_both": sorted(source_ids & corpus_ids),
        "only_in_source": sorted(source_ids - corpus_ids),
        "only_in_corpus": sorted(corpus_ids - source_ids),
        "values": sorted(values, key=lambda v: v["mis_id"]),
    }


def build_report(
    source_path: Path,
    corpus_path: Path,
    provenance_path: Path | None,
    dump_key: str | None = None,
) -> dict[str, Any]:
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = None
    if provenance_path is not None and provenance_path.is_file():
        expected = json.loads(provenance_path.read_text(encoding="utf-8")).get("source_sha256")
    rows = flatten_source(json.loads(raw.decode("utf-8")))
    linked = corpus_empty_ids(corpus_path)
    source_ids = {str(r.get("mis_id")) for r in rows}
    all_target_ids = linked | set(A3_MIS_IDS)
    universal = universal_keys(rows, all_target_ids)

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
        "universal_meta_keys": sorted(universal),
        "all_targets": probe(rows, all_target_ids, universal),
        "a3": {mid: probe(rows, {mid}, universal) for mid in A3_MIS_IDS},
    }
    if dump_key is not None:
        report["dump"] = dump_key_rows(rows, dump_key, corpus_path)
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
    parser.add_argument(
        "--dump-key",
        default=None,
        help="2차 실행: 이 키의 값 전체와 코퍼스 '원본+공란' 행과의 일치를 보고서에 싣는다",
    )
    args = parser.parse_args(argv)

    for label, path in (("원천", args.source), ("코퍼스", args.corpus)):
        if not path.is_file():
            print(f"[!] {label} 파일 없음: {path}", file=sys.stderr)
            return 2
    try:
        report = build_report(args.source, args.corpus, args.provenance, args.dump_key)
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
