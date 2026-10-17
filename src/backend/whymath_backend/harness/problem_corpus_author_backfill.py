"""코퍼스 저작 서명(`authored_by`) 백필 CLI — 기존 결정론 생성 코퍼스에 서명을 심는다(PB-17).

배경: PB-15가 생성자≠검증자 가드를 3상태(`llm:`·`deterministic:`·기록 없음=거부)로 바꿨으나,
서명을 찍는 쪽은 LLM 생성기뿐이었다. 결정론 스켈레톤 생성기가 만든 기존 코퍼스
(`data/corpus/problem_bank_*`)는 `authored_by`가 없어 잔여 축 교차검증 게이트
(`residue_cross_verify_eval`)에서 `INDEPENDENCE_UNPROVEN`으로 거부됐다. 신규 생성분은 생성기
데코레이터(`l3.equivalent.generator.deterministic_generator`)가 생성 시점에 서명하고, 이 CLI는
**이미 존재하는 코퍼스**를 백필한다.

도출 원칙 — 추측하지 않는다. 서명은 디렉터리의 `_provenance.json`에 *이미 적힌 생성기 사실*에서만
도출한다:
  ① `generation_method`가 LLM 개입을 말하면(`LLM 0`이 아닌 `LLM …`) 결정론으로 단정하지 않는다.
     (예 `problem_bank_rephrased_v0` = LLM 발문 재작성 — 모델 id가 기록돼 있지 않아 `llm:<모델>`
     서명도 지어내지 않는다) → **미백필·사유**로 보고.
  ② 사람 저작(`hand-authored`·`사람 저작`)은 결정론 *생성기*가 아니므로 → 미백필·사유.
  ③ `generation_method`가 `l3/equivalent/<X>.py` 한 개를 지목하고 그 `X`가 결정론 생성기 데코레이터
     등록부(코드)에 실재하면 → `deterministic:X`  (근거: 지목 + 등록부 실재).
  ④ 지목이 글롭(`*_skeleton_generator.py`)이거나 파일명 역추적이 실패했으면, `LLM 0` 선언이 있을
     때에 한해 오케스트레이션 배치 모듈(`harness/<B>.py` 또는 `generation_cli`, 또는 코드에서
     `CORPUS_DIR_NAME`이 이 디렉터리를 가리키는 배치 모듈)에서 도출 — 그 배치 모듈이 등록된 결정론
     생성기 모듈을 정확히 1개 임포트하면 그 이름, 아니면 배치 모듈 이름 → `deterministic:…`.
  ⑤ 어느 근거도 못 얻으면 미백필·사유.

레코드 단위 불변:
  - 이미 `authored_by`가 있는 레코드는 손대지 않는다(기록이 선언보다 우선 — PB-17 ③).
  - `generation_type`이 `FULLY_GENERATED`가 아닌 레코드는 서명하지 않는다(미백필·사유로 건수 보고).
  - 서명 필드 한 키만 추가한다 — 키 위치는 `problem_corpus_batch._record_to_json`의 직렬화
    순서(`generation_type`/`original_source` 뒤, `concepts` 앞)와 같아, 같은 생성기를 재실행한
    출력과 바이트 동일하다.

바이트·건수 계약(대용량 JSON 재작성 안전):
  - 줄 단위 `json.loads` → `json.dumps(ensure_ascii=False)` 라운드트립이 원문 줄과 **바이트 동일**한
    경우에만 재작성한다(불일치면 그 디렉터리를 쓰지 않고 실패 — 서식 변경으로 diff 가 부풀지 않게).
  - 쓰기 전 단언: 레코드(줄) 수 불변 · 서명 키를 제거하면 원 레코드와 동일 · 총 증가 바이트 수가
    `"authored_by": "…", ` 조각 길이의 합과 정확히 일치.
  - 멱등: 2회 실행은 변경 0건.

사용법(레포 루트에서):
    python -m whymath_backend.harness.problem_corpus_author_backfill
        (제자리 백필)
    python -m whymath_backend.harness.problem_corpus_author_backfill --dry-run
        (통계만 — 항상 exit 0)
    python -m whymath_backend.harness.problem_corpus_author_backfill --check
        (드리프트 가드 — 서명 가능한데 빠진 레코드가 1건이라도 있으면 exit 1.
         CI 가 레포 데이터를 재작성하지 않는다)

harness는 import-linter 계약 밖(조성/ops 층 — problem_corpus_batch 선례).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import pkgutil
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l3.cross_verify import deterministic_author
from whymath_backend.l3.equivalent.generator import DETERMINISTIC_GENERATOR_MARK

__all__ = [
    "AuthorDecision",
    "AuthorBackfillReport",
    "CorpusDirResult",
    "derive_corpus_author",
    "main",
    "registered_deterministic_generators",
    "run_author_backfill",
]

_AUTHOR_KEY = "authored_by"
_FULLY_GENERATED = "FULLY_GENERATED"
_EQUIVALENT_PACKAGE = "whymath_backend.l3.equivalent"

_RE_GENERATOR_FILE = re.compile(r"l3/equivalent/([A-Za-z0-9_]+)\.py")
_RE_HARNESS_FILE = re.compile(r"harness/([A-Za-z0-9_]+)\.py")
_RE_HARNESS_CLI = re.compile(r"whymath_backend\.harness\.([A-Za-z0-9_]+)")
_RE_LLM_ZERO = re.compile(r"LLM\s*0")
_RE_LLM_INVOLVED = re.compile(r"LLM(?!\s*0)")
_RE_HUMAN = re.compile(r"hand-authored|사람 저작")


def registered_deterministic_generators() -> frozenset[str]:
    """결정론 생성기 데코레이터 등록부(코드) — 표식이 찍힌 클래스가 사는 모듈 이름 집합.

    `l3/equivalent` 패키지의 모든 모듈을 임포트해 실측한다(하드코딩 목록 금지). 0건이면 실패한다
    — 스캔이 공허하게 끝난 등록부로 도출하면 모든 코퍼스가 미백필로 위장된다.
    """
    package = importlib.import_module(_EQUIVALENT_PACKAGE)
    names: set[str] = set()
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{_EQUIVALENT_PACKAGE}.{info.name}")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == module.__name__
                and DETERMINISTIC_GENERATOR_MARK in vars(value)
            ):
                names.add(info.name)
    if not names:
        raise RuntimeError("결정론 생성기 등록부가 0건 — 스캔 실패(공허 통과 금지)")
    return frozenset(names)


@dataclass(frozen=True, slots=True)
class AuthorDecision:
    """디렉터리 단위 도출 결과 — `signature`가 None 이면 미백필(`reason`이 사유)."""

    signature: str | None
    evidence: str  # 도출 경로(감사용)
    reason: str = ""  # 미백필 사유(signature None 일 때)


def _batch_module_for_dir(corpus_dir_name: str, harness_dir: Path) -> str | None:
    """코드에서 `CORPUS_DIR_NAME`이 이 디렉터리를 가리키는 배치 모듈 이름(정확히 1개일 때만)."""
    pattern = re.compile(rf'^CORPUS_DIR_NAME\s*=\s*"{re.escape(corpus_dir_name)}"\s*$', re.M)
    hits = [
        path.stem
        for path in sorted(harness_dir.glob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    return hits[0] if len(hits) == 1 else None


def _imported_generators(
    batch_module: str, harness_dir: Path, registered: frozenset[str]
) -> list[str]:
    """배치 모듈이 임포트하는 등록된 결정론 생성기 모듈 이름들(AST — 문자열 검색 아님)."""
    path = harness_dir / f"{batch_module}.py"
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    prefix = f"{_EQUIVALENT_PACKAGE}."
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefix):
            stem = node.module[len(prefix) :]
            if stem in registered:
                found.add(stem)
    return sorted(found)


def derive_corpus_author(
    provenance: dict[str, Any],
    *,
    corpus_dir_name: str,
    registered: frozenset[str],
    harness_dir: Path,
) -> AuthorDecision:
    """`_provenance.json` 사실 → 디렉터리 서명 결정(위 ①~⑤). 추측하지 않는다."""
    method = provenance.get("generation_method")
    if not isinstance(method, str) or not method.strip():
        return AuthorDecision(None, "", "generation_method 부재 — 저작 주체를 도출할 사실이 없다")
    if _RE_HUMAN.search(method):
        return AuthorDecision(None, "", "사람 저작 시드 — 결정론 생성기가 만든 것이 아니다")
    if _RE_LLM_INVOLVED.search(method):
        return AuthorDecision(
            None,
            "",
            "LLM 개입(발문 재작성 등) — 결정론으로 단정할 수 없고 저작 모델 id 도 기록돼 있지 않다",
        )

    named = sorted(set(_RE_GENERATOR_FILE.findall(method)))
    if len(named) == 1 and named[0] in registered:
        return AuthorDecision(
            deterministic_author(named[0]), f"generation_method 지목 + 등록부 실재: {named[0]}"
        )
    if len(named) == 1:
        return AuthorDecision(
            None, "", f"지목된 생성기 {named[0]!r}가 결정론 생성기 등록부에 없다(데코레이터 미부착)"
        )

    # 글롭·역추적 실패·복수 지목 — 'LLM 0' 선언이 있어야 한다(사실 근거).
    if not _RE_LLM_ZERO.search(method):
        return AuthorDecision(
            None, "", "생성기 파일 지목이 없고 'LLM 0' 선언도 없어 결정론 여부를 도출할 수 없다"
        )
    batch: str | None = None
    for finder in (_RE_HARNESS_FILE, _RE_HARNESS_CLI):
        cli = str(provenance.get("generation_cli", ""))
        found = sorted(set(finder.findall(method)) | set(finder.findall(cli)))
        if len(found) == 1:
            batch = found[0]
            break
    evidence = "LLM 0 선언 + 배치 모듈 지목"
    if batch is None:
        batch = _batch_module_for_dir(corpus_dir_name, harness_dir)
        evidence = "LLM 0 선언 + CORPUS_DIR_NAME 배치 모듈 실측"
    if batch is None:
        return AuthorDecision(
            None, "", "'LLM 0' 선언은 있으나 생성기/배치 모듈을 특정할 근거가 없다(역추적 실패)"
        )
    imported = _imported_generators(batch, harness_dir, registered)
    if len(imported) == 1:
        return AuthorDecision(
            deterministic_author(imported[0]), f"{evidence}({batch}) → 임포트 생성기 {imported[0]}"
        )
    return AuthorDecision(
        deterministic_author(batch),
        f"{evidence}({batch}) — 생성기 {len(imported)}종 임포트라 배치 모듈 이름으로 서명",
    )


@dataclass(slots=True)
class CorpusDirResult:
    """디렉터리 1개 결과."""

    name: str
    records: int = 0
    stamped: int = 0  # 이번 실행에서 서명을 추가한(또는 --check/--dry-run 에서 추가할) 레코드
    already_signed: int = 0
    skipped_not_fully_generated: int = 0
    signature: str | None = None
    evidence: str = ""
    unbackfilled_reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "records": self.records,
            "stamped": self.stamped,
            "already_signed": self.already_signed,
            "skipped_not_fully_generated": self.skipped_not_fully_generated,
            "signature": self.signature,
            "evidence": self.evidence,
            "unbackfilled_reason": self.unbackfilled_reason,
        }


@dataclass(slots=True)
class AuthorBackfillReport:
    """전체 결과 — `unbackfilled`가 '미백필·사유' 목록이다."""

    dirs: list[CorpusDirResult] = field(default_factory=list)

    @property
    def total_records(self) -> int:
        return sum(d.records for d in self.dirs)

    @property
    def total_stamped(self) -> int:
        return sum(d.stamped for d in self.dirs)

    @property
    def unbackfilled(self) -> list[CorpusDirResult]:
        return [d for d in self.dirs if d.signature is None]

    def to_json(self) -> dict[str, Any]:
        return {
            "total_dirs": len(self.dirs),
            "total_records": self.total_records,
            "total_stamped": self.total_stamped,
            "unbackfilled": [
                {"name": d.name, "records": d.records, "reason": d.unbackfilled_reason}
                for d in self.unbackfilled
            ],
            "dirs": [d.to_json() for d in self.dirs],
        }


def _insert_signature(record: dict[str, Any], signature: str) -> dict[str, Any]:
    """`problem_corpus_batch._record_to_json` 직렬화 순서대로 서명 키를 끼운다."""
    anchor = "original_source" if "original_source" in record else "generation_type"
    if anchor not in record:
        raise ValueError("generation_type 키가 없는 레코드 — 서명 위치를 정할 수 없다")
    out: dict[str, Any] = {}
    for key, value in record.items():
        out[key] = value
        if key == anchor:
            out[_AUTHOR_KEY] = signature
    return out


def _backfill_text(text: str, signature: str, result: CorpusDirResult) -> str:
    """JSONL 본문 → 서명 추가본(필요 없으면 원문 그대로). 위 바이트·건수 계약을 단언한다."""
    if "\r" in text:
        raise ValueError("CRLF 줄바꿈 — 기존 포맷(LF)과 달라 안전하게 재작성할 수 없다")
    lines = text.split("\n")
    out_lines: list[str] = []
    added_bytes = 0
    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue
        record = json.loads(line)
        if json.dumps(record, ensure_ascii=False) != line:
            raise ValueError("라운드트립 불일치 — 기존 직렬화 서식을 보존할 수 없어 쓰지 않는다")
        result.records += 1
        if _AUTHOR_KEY in record:
            result.already_signed += 1
            out_lines.append(line)
            continue
        if record.get("generation_type") != _FULLY_GENERATED:
            result.skipped_not_fully_generated += 1
            out_lines.append(line)
            continue
        updated = _insert_signature(record, signature)
        new_line = json.dumps(updated, ensure_ascii=False)
        # 서명 키를 빼면 원 레코드와 같아야 한다(서명 필드만 추가).
        if {k: v for k, v in updated.items() if k != _AUTHOR_KEY} != record:
            raise AssertionError("서명 외 필드가 변했다")
        added_bytes += len(f'"{_AUTHOR_KEY}": {json.dumps(signature, ensure_ascii=False)}, ')
        out_lines.append(new_line)
        result.stamped += 1
    new_text = "\n".join(out_lines)
    if len(out_lines) != len(lines):
        raise AssertionError("줄 수가 변했다")
    if len(new_text) - len(text) != added_bytes:
        raise AssertionError(
            f"증가 길이 불일치: 실제 {len(new_text) - len(text)} != 기대 {added_bytes}"
        )
    return new_text


def run_author_backfill(
    corpus_root: Path, *, harness_dir: Path | None = None, write: bool = True
) -> AuthorBackfillReport:
    """`corpus_root/problem_bank_*/problems.jsonl` 전수 백필. `write=False`면 파일을 쓰지 않는다."""
    resolved_harness = harness_dir if harness_dir is not None else Path(__file__).resolve().parent
    registered = registered_deterministic_generators()
    report = AuthorBackfillReport()
    problem_files = sorted(corpus_root.glob("problem_bank_*/problems.jsonl"))
    if not problem_files:
        raise FileNotFoundError(f"{corpus_root}에 problem_bank_*/problems.jsonl 이 0건 — 스캔 실패")
    for problems_path in problem_files:
        directory = problems_path.parent
        result = CorpusDirResult(name=directory.name)
        report.dirs.append(result)
        provenance_path = directory / "_provenance.json"
        provenance: dict[str, Any] = (
            json.loads(provenance_path.read_text(encoding="utf-8"))
            if provenance_path.exists()
            else {}
        )
        decision = derive_corpus_author(
            provenance,
            corpus_dir_name=directory.name,
            registered=registered,
            harness_dir=resolved_harness,
        )
        text = problems_path.read_text(encoding="utf-8")
        if decision.signature is None:
            result.unbackfilled_reason = decision.reason
            # 레코드 수만 센다(쓰지 않는다).
            result.records = sum(1 for line in text.split("\n") if line.strip())
            continue
        result.signature = decision.signature
        result.evidence = decision.evidence
        new_text = _backfill_text(text, decision.signature, result)
        if write and new_text != text:
            problems_path.write_text(new_text, encoding="utf-8", newline="")
    return report


def _default_corpus_root() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "corpus"


def main(argv: list[str] | None = None) -> int:
    """CLI — 기본 제자리 백필 · `--dry-run` 관측(항상 exit 0) · `--check` 드리프트 가드."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_author_backfill",
        description="코퍼스 저작 서명(authored_by) 백필 — _provenance.json 사실에서만 도출(PB-17).",
    )
    parser.add_argument("--root", type=Path, default=None, help="코퍼스 루트(기본 data/corpus).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="파일 미기록·통계만(항상 exit 0).")
    mode.add_argument(
        "--check", action="store_true", help="미기록·서명 가능한데 빠진 레코드가 있으면 exit 1."
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else _default_corpus_root()
    report = run_author_backfill(root, write=not (args.dry_run or args.check))
    sys.stdout.write(json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n")
    if args.check and report.total_stamped > 0:
        sys.stderr.write(
            f"서명 누락 {report.total_stamped}건 — `python -m "
            "whymath_backend.harness.problem_corpus_author_backfill`로 백필하라.\n"
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
