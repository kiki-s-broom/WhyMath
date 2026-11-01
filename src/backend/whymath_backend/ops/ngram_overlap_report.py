"""LLM 저작 산출물의 8-gram 일치율 **기록기** — EOS-222 (감리 W-19·W-21·W-22).

무엇을 하는가
------------
`docs/legal/copyright_guide_v2.md`의 n-gram 가드레일(8-gram · 일치율 70% 이상이면 재생성)을
저작 회차 산출물(`data/runs/<회차>/cu.jsonl`)의 발문(`question_text`)·해설
(`answer_explanation`)마다 계산해 회차 폴더의 사이드카 `cu.ngram_overlap.json`에 **기록**한다.

이 모듈은 **차단하지 않는다**. 일치율이 기준을 넘어도 종료 코드는 0이며, 넘은 건은
`flagged`에 CU slug와 함께 적힌다. 재생성 여부는 사람이 이 기록을 보고 정한다(감리 지시:
"차단이 아니라 기록").

일치율의 정의 (가이드 예시 코드의 식 · 경계만 다름)
---------------------------------------------------
    overlap(G, O) = |8gram(G) ∩ 8gram(O)| / |8gram(G)|

G는 생성 필드 하나, O는 비교 원본 문서 하나다. 원본마다 계산해 **최댓값**과 그 원본을
기록한다. 기준 비교는 `overlap >= 0.70`이다 — 가이드 예시 코드는 `> threshold`지만 태스크
acceptance와 가이드 본문이 "70% 이상"이라 경계값 0.70을 기준 이상으로 센다.

토큰화는 NFKC 정규화 뒤 공백 분리다(`TOKENIZER_ID`) — 가이드가 토큰화를 정하지 않았으므로
무엇으로 쟀는지를 산출물에 남긴다. **이 토큰화는 일치율을 낮게 잡는 쪽으로 틀린다**: 띄어쓰기
하나(`x 의`→`x의`, `y = x`→`y=x`)가 그 토큰을 지나는 8-gram을 전부 지우므로, 띄어쓰기만 바꾼
복사도 기준 아래로 내려갈 수 있다. 그래서 낮은 값은 "다르다"의 증거가 아니다(산출물 `limitation`).

회차 뒤 코퍼스에 병합된 자기 자신과의 일치는 세지 않는다 — 비교 원본 중 CU와 slug가 같은
문서는 제외한다(`method.self_slug_excluded`).

측정하지 않은 것을 0%로 쓰지 않는다
-----------------------------------
- 필드가 없거나 토큰이 8개 미만이면 `status="unmeasurable"`과 이유를 적는다(값 없음).
- 비교 원본 문서가 0건이면(입력 기록 없음·코퍼스가 저장소에 없음) 전 필드가
  `unmeasurable`("비교 원본 0건")이다 — 대조하지 않은 것을 0%로 쓰지 않는다.
- 입력 중 대조하지 않은 경로(회차 자기 산출물·`problems.jsonl`이 아닌 입력)는
  `skipped_inputs`에, 해시가 회차 기록과 다르거나 저장소에 없는 코퍼스는
  `summary.comparison_warnings`에 남는다(조용히 버리지 않는다).
- 비교 원본은 **저장소에 실재하는 것만** 쓴다: 그 회차가 실제로 읽은 입력 코퍼스
  (`cu.rounds.jsonl`의 `dedup_input_digests`)에서 회차 자기 산출물을 뺀 것.
- 평가원·EBS·검정교과서 본문은 저장소에 없어서(본문 복제 금지) **대조하지 못한다**. 이
  한계는 산출물의 `not_compared`에 적힌다 — "일치율 낮음"은 "그 원본들과 다르다"는 뜻이
  아니다.

사용
----
    # 회차 하나를 계산해 사이드카를 쓴다
    python -m whymath_backend.ops.ngram_overlap_report run data/runs/eos197-a6-openrouter

    # 코퍼스 하나를 비교 코퍼스와 대조한 요약 JSON을 출력한다(쓰기 없음)
    python -m whymath_backend.ops.ngram_overlap_report corpus \\
        data/corpus/problem_bank_rephrased_v0 --against data/corpus/problem_bank_generated_v0

종료 코드: 0 = 계산·기록 완료(넘은 건이 있어도 0) · 2 = 입력 오류(경로·JSON 파싱 실패).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

N: Final = 8
THRESHOLD: Final = 0.70
TOKENIZER_ID: Final = "nfkc-whitespace-v1"
GUIDE_REF: Final = "docs/legal/copyright_guide_v2.md (n-gram 가드레일 · 8-gram · 70% 이상 재생성)"
SIDECAR_NAME: Final = "cu.ngram_overlap.json"
FIELDS: Final = ("question_text", "answer_explanation")

LIMITATION: Final = (
    "일치율이 낮다는 것은 comparison_set과 다르다는 뜻일 뿐이다 — not_compared의 원본과는"
    " 대조하지 않았다. 또 공백 분리 토큰화라 띄어쓰기만 바꾼 복사도 낮게 나오고(과소평가),"
    " 토큰 8개 미만 필드는 잴 수 없다(unmeasurable). 낮은 값은 '다르다'의 증거가 아니다."
)

# 저장소에 본문이 없어 대조할 수 없는 원본 — 산출물에 그대로 적는다.
NOT_COMPARED: Final = (
    "평가원 기출 본문(저장소 미보유 — 구조 메타만 보유)",
    "EBS 교재·강의 본문(저장소 미보유)",
    "검정교과서 본문·문제·풀이(저장소 미보유)",
)


def tokenize(text: str) -> list[str]:
    """NFKC 정규화 뒤 공백 분리."""
    return unicodedata.normalize("NFKC", text).split()


def ngrams(tokens: Sequence[str], n: int = N) -> set[tuple[str, ...]]:
    """토큰 열의 n-gram 집합(토큰이 n개 미만이면 빈 집합)."""
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


@dataclass(frozen=True, slots=True)
class OriginalDoc:
    """비교 원본 문서 하나 — 어느 코퍼스의 어느 레코드·필드인지."""

    corpus: str
    slug: str
    field: str
    grams: frozenset[tuple[str, ...]]


class OriginalIndex:
    """n-gram → 원본 문서 역색인. 원본 수천 건과의 최댓값을 빠르게 구한다."""

    def __init__(self, docs: Iterable[OriginalDoc]) -> None:
        self.docs: list[OriginalDoc] = [d for d in docs if d.grams]
        self._index: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i, doc in enumerate(self.docs):
            for g in doc.grams:
                self._index[g].append(i)

    def best_match(
        self, grams: set[tuple[str, ...]], exclude_slug: str | None = None
    ) -> tuple[float, OriginalDoc | None]:
        """가장 많이 겹치는 원본과 그 일치율. 겹침이 없으면 (0.0, None).

        `exclude_slug`와 slug가 같은 원본은 세지 않는다(회차 뒤 병합된 자기 자신).
        """
        counts: dict[int, int] = defaultdict(int)
        for g in grams:
            for i in self._index.get(g, ()):
                if exclude_slug is not None and self.docs[i].slug == exclude_slug:
                    continue
                counts[i] += 1
        if not counts:
            return 0.0, None
        best_i = max(counts, key=lambda i: (counts[i], -i))
        return counts[best_i] / len(grams), self.docs[best_i]


def measure_field(
    text: object, index: OriginalIndex, self_slug: str | None = None
) -> dict[str, object]:
    """필드 하나의 일치율 기록. 측정할 수 없으면 값 없이 이유만 적는다."""
    if not index.docs:
        return {"status": "unmeasurable", "reason": "비교 원본 0건"}
    if not isinstance(text, str) or not text.strip():
        return {"status": "unmeasurable", "reason": "필드 없음"}
    tokens = tokenize(text)
    grams = ngrams(tokens)
    if not grams:
        return {"status": "unmeasurable", "reason": f"토큰 {len(tokens)}개 < {N}"}
    overlap, doc = index.best_match(grams, exclude_slug=self_slug)
    return {
        "status": "measured",
        "overlap": round(overlap, 4),
        "ngram_count": len(grams),
        "at_or_above_threshold": overlap >= THRESHOLD,
        "best_match": (
            None if doc is None else {"corpus": doc.corpus, "slug": doc.slug, "field": doc.field}
        ),
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"{path}:{line_no} JSON 파싱 실패({type(exc).__name__})") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


class InputError(Exception):
    """입력 경로·형식 오류 — 종료 코드 2."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_match(path: Path, recorded: set[str]) -> str:
    """회차가 기록한 입력 해시와 지금 저장소 파일의 관계.

    회차는 Kiki 머신(Windows · CRLF 체크아웃)에서 돌아 같은 내용이라도 해시가 다르다.
    그래서 줄바꿈만 다른 경우를 따로 구분한다 — 'mismatch'를 '내용이 바뀌었다'로만 읽도록.
    """
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() in recorded:
        return "exact"
    lf = raw.replace(b"\r\n", b"\n")
    if hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest() in recorded:
        return "crlf_equivalent"
    if hashlib.sha256(lf).hexdigest() in recorded:
        return "lf_equivalent"
    return "mismatch"


def load_corpus_docs(problems_path: Path, corpus: str) -> list[OriginalDoc]:
    """코퍼스 `problems.jsonl`의 발문·해설을 원본 문서로 읽는다."""
    docs: list[OriginalDoc] = []
    for row in _read_jsonl(problems_path):
        slug = str(row.get("slug", ""))
        for field in FIELDS:
            text = row.get(field)
            if isinstance(text, str) and text.strip():
                docs.append(OriginalDoc(corpus, slug, field, frozenset(ngrams(tokenize(text)))))
    return docs


def measure_records(
    records: Sequence[dict[str, object]], index: OriginalIndex
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """레코드마다 필드별 일치율을 재고 요약을 낸다."""
    results: list[dict[str, object]] = []
    flagged: list[dict[str, object]] = []
    measured = unmeasurable = 0
    max_overlap: float | None = None
    by_field: dict[str, dict[str, object]] = {
        f: {"measured": 0, "unmeasurable": 0, "max_overlap": None, "flagged_count": 0}
        for f in FIELDS
    }
    for row in records:
        slug = str(row.get("slug", ""))
        fields = {f: measure_field(row.get(f), index, self_slug=slug or None) for f in FIELDS}
        for f, rec in fields.items():
            bf = by_field[f]
            if rec["status"] == "measured":
                measured += 1
                bf["measured"] = int(bf["measured"]) + 1  # type: ignore[call-overload]
                ov = float(rec["overlap"])  # type: ignore[arg-type]
                max_overlap = ov if max_overlap is None else max(max_overlap, ov)
                prev = bf["max_overlap"]
                bf["max_overlap"] = ov if prev is None else max(float(prev), ov)  # type: ignore[arg-type]
                if rec["at_or_above_threshold"]:
                    flagged.append({"slug": slug, "field": f, "overlap": rec["overlap"]})
                    bf["flagged_count"] = int(bf["flagged_count"]) + 1  # type: ignore[call-overload]
            else:
                unmeasurable += 1
                bf["unmeasurable"] = int(bf["unmeasurable"]) + 1  # type: ignore[call-overload]
        results.append({"slug": slug, "fields": fields})
    summary: dict[str, object] = {
        "records": len(records),
        "fields_measured": measured,
        "fields_unmeasurable": unmeasurable,
        "max_overlap": max_overlap,
        "flagged_count": len(flagged),
        "by_field": by_field,
        "flagged": flagged,
    }
    return results, summary


def _method() -> dict[str, object]:
    return {
        "n": N,
        "threshold": THRESHOLD,
        "threshold_rule": (
            "overlap >= threshold 이면 at_or_above_threshold=true (기록만 — 차단 없음)"
        ),
        "formula": "|8gram(G) ∩ 8gram(O)| / |8gram(G)| 의 원본별 최댓값",
        "tokenizer": TOKENIZER_ID,
        "tokenizer_bias": "공백 분리라 띄어쓰기만 바꾼 복사도 일치율이 낮게 나온다(과소평가 방향)",
        "self_slug_excluded": True,
        "fields": list(FIELDS),
        "guide": GUIDE_REF,
    }


def _run_input_corpora(
    run_dir: Path, repo_root: Path
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """회차가 실제로 읽은 입력 코퍼스(자기 산출물 제외)를 저장소 경로로 되짚는다.

    대조하지 않은 입력은 버리지 않고 (경로, 이유)로 돌려준다.
    """
    rounds_path = run_dir / "cu.rounds.jsonl"
    if not rounds_path.exists():
        raise InputError(f"{rounds_path} 없음 — 회차 입력 코퍼스를 알 수 없다")
    recorded: dict[str, set[str]] = defaultdict(set)
    raw_paths: dict[str, set[str]] = defaultdict(set)
    skipped: dict[str, str] = {}
    for row in _read_jsonl(rounds_path):
        digests = row.get("dedup_input_digests") or {}
        if not isinstance(digests, dict):
            continue
        for raw_path, digest in digests.items():
            parts = str(raw_path).replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[-2] == run_dir.name and parts[-1] == "cu.jsonl":
                skipped[str(raw_path)] = "회차 자기 산출물"
                continue
            if len(parts) < 2 or parts[-1] != "problems.jsonl":
                skipped[str(raw_path)] = "problems.jsonl이 아닌 입력 — 대조 미지원"
                continue
            recorded[parts[-2]].add(str(digest))
            raw_paths[parts[-2]].add(str(raw_path))
    corpora: list[dict[str, object]] = []
    for name in sorted(recorded):
        path = repo_root / "data" / "corpus" / name / "problems.jsonl"
        if not path.exists():
            corpora.append(
                {
                    "corpus": name,
                    "status": "missing_in_repo",
                    "run_paths": sorted(raw_paths[name]),
                    "run_digests": sorted(recorded[name]),
                }
            )
            continue
        sha = _sha256(path)
        corpora.append(
            {
                "corpus": name,
                "path": path.relative_to(repo_root).as_posix(),
                "sha256": sha,
                "run_paths": sorted(raw_paths[name]),
                "run_digests": sorted(recorded[name]),
                "digest_match": digest_match(path, recorded[name]),
            }
        )
    skipped_list = [{"path": k, "reason": v} for k, v in sorted(skipped.items())]
    return corpora, skipped_list


def build_run_report(run_dir: Path, repo_root: Path) -> dict[str, object]:
    """회차 사이드카 payload를 만든다(쓰기 없음)."""
    cu_path = run_dir / "cu.jsonl"
    if not cu_path.exists():
        raise InputError(f"{cu_path} 없음")
    corpora, skipped = _run_input_corpora(run_dir, repo_root)
    docs: list[OriginalDoc] = []
    warnings: list[str] = []
    for c in corpora:
        if "path" not in c:
            warnings.append(f"{c['corpus']}: 저장소에 없음 — 대조 못 함")
            continue
        loaded = load_corpus_docs(repo_root / str(c["path"]), str(c["corpus"]))
        docs.extend(loaded)
        c["documents"] = sum(1 for d in loaded if d.grams)  # 실제로 대조한 문서 수
        if c.get("digest_match") == "mismatch":
            warnings.append(
                f"{c['corpus']}: 회차가 읽은 판과 내용이 다름 — 지금 저장소 판으로 쟀다"
            )
    index = OriginalIndex(docs)
    if not index.docs:
        warnings.append("비교 원본 0건 — 전 필드 측정 불가")
    results, summary = measure_records(_read_jsonl(cu_path), index)
    summary["comparison_warnings"] = warnings
    return {
        "kind": "whymath.ngram_overlap_record",
        "task": "EOS-222",
        "run": run_dir.name,
        "cu_sha256": _sha256(cu_path),
        "method": _method(),
        "comparison_set": corpora,
        "comparison_set_rule": (
            "그 회차가 실제로 읽은 입력 코퍼스(cu.rounds.jsonl dedup_input_digests)에서"
            " 회차 자기 산출물을 뺀 것"
        ),
        "skipped_inputs": skipped,
        "not_compared": list(NOT_COMPARED),
        "limitation": LIMITATION,
        "summary": summary,
        "results": results,
    }


def build_corpus_summary(
    corpus_dir: Path, against: Sequence[Path], repo_root: Path
) -> dict[str, object]:
    """코퍼스 하나를 비교 코퍼스와 대조한 요약(사이드카 `similarity_8gram` 값용)."""
    target = corpus_dir / "problems.jsonl"
    if not target.exists():
        raise InputError(f"{target} 없음")
    docs: list[OriginalDoc] = []
    comparison: list[dict[str, object]] = []
    for a in against:
        path = a / "problems.jsonl"
        if not path.exists():
            raise InputError(f"{path} 없음")
        loaded = load_corpus_docs(path, a.name)
        docs.extend(loaded)
        resolved = path.resolve()
        shown = (
            resolved.relative_to(repo_root).as_posix()
            if resolved.is_relative_to(repo_root)
            else resolved.as_posix()
        )
        comparison.append(
            {
                "corpus": a.name,
                "path": shown,
                "sha256": _sha256(path),
                "documents": sum(1 for d in loaded if d.grams),
            }
        )
    _, summary = measure_records(_read_jsonl(target), OriginalIndex(docs))
    flagged = summary.pop("flagged")
    assert isinstance(flagged, list)
    summary["flagged_question_text_slugs"] = sorted(
        str(f["slug"]) for f in flagged if isinstance(f, dict) and f.get("field") == "question_text"
    )
    return {
        "task": "EOS-222",
        "target_sha256": _sha256(target),
        "method": _method(),
        "comparison_set": comparison,
        "not_compared": list(NOT_COMPARED),
        "limitation": LIMITATION,
        "summary": summary,
    }


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "data" / "corpus").is_dir():
            return p
    return Path.cwd()


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM 저작 산출물 8-gram 일치율 기록기(EOS-222 — 차단 없음)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="회차 폴더를 계산해 cu.ngram_overlap.json을 쓴다")
    p_run.add_argument("run_dirs", nargs="+", type=Path)
    p_run.add_argument("--dry-run", action="store_true", help="쓰지 않고 요약만 출력")
    p_corpus = sub.add_parser("corpus", help="코퍼스 요약 JSON을 표준출력에 낸다(쓰기 없음)")
    p_corpus.add_argument("corpus_dir", type=Path)
    p_corpus.add_argument("--against", type=Path, action="append", required=True)
    p_corpus.add_argument("--root", type=Path, default=None)
    p_run.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = (args.root or _repo_root()).resolve()
    try:
        if args.cmd == "corpus":
            sys.stdout.write(_dump(build_corpus_summary(args.corpus_dir, args.against, root)))
            return 0
        for run_dir in args.run_dirs:
            report = build_run_report(run_dir, root)
            s = report["summary"]
            print(f"[{run_dir.name}] {_dump(s).strip()}")
            if not args.dry_run:
                (run_dir / SIDECAR_NAME).write_text(_dump(report), encoding="utf-8")
                print(f"  기록: {run_dir / SIDECAR_NAME}")
        return 0
    except (InputError, OSError) as exc:
        print(f"입력 오류({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
