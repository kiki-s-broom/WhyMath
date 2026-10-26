"""PB-20 — 변형 코퍼스 편입 결정(스테이징)이 실제 노출 경로의 게이트를 경유함을 동결한다.

결정: PB-09 산출물을 `data/corpus/problem_variants_staging_v0/`(= `problem_bank_*` 글롭 **밖**)에
커밋하고, 검수 표본 감사(Wilson 게이트)를 통과해야만 글롭 안으로 옮긴다.
정본: `docs/architecture/problem_bank_variant_intake_pb20.md`.

정본화와 집행은 별항이다 — 아래 테스트가 "결정이 문서에만 있지 않음"을 기계로 보인다.

  ① 로트 동결 — 행 수·sha256이 사이드카와 같다(감사 라벨이 다른 로트의 것이 되는 것을 막는다)
  ② 노출 글롭 밖 — 소스·스크립트의 모든 `problem_bank*` 글롭이 스테이징 디렉터리와 일치하지 않는다
     (양성 대조군: 같은 글롭들이 실제 코퍼스에는 일치한다 — 스캐너가 눈먼 것이 아님)
  ③ 서빙 게이트 — 스테이징 행은 검수 공백이고, 서빙 술어(`is_review_cleared`·CAT 후보 풀)는
     `approved`만 통과시킨다
  ④ 승격 시 근거 차용 금지 — 다른 코퍼스의 감사 근거로 스테이징을 각인하려는 시도는 거부된다
  ⑤ 로트 크기 사실 — 모드별로 쪼개면 감사 최소 표본(n≥200)에 도달할 수 없다(쪼개기 금지의 근거)
  ⑥ 조사 문서의 소비처 목록이 글롭을 쓰는 모든 파일을 포함한다(새 소비처 → 분류 전까지 RED)
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from whymath_backend.harness.problem_corpus_review_status_backfill import _MIN_N
from whymath_backend.harness.review_status_domains import (
    classify_corpus,
    corpus_backfill_refusal,
)
from whymath_backend.l1.problem_bank.populate import (
    discover_problem_corpora,
    load_problem_bank_records,
)
from whymath_backend.l2.next_problem_selection import candidate_pool_conditions
from whymath_backend.l6._shared import is_review_cleared
from whymath_backend.ops.provenance_audit import audit_corpus_root
from whymath_backend.schema.enums import ReviewStatus, is_review_status_cleared

_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _ROOT / "data" / "corpus"
_STAGING_NAME = "problem_variants_staging_v0"
_STAGING = _CORPUS / _STAGING_NAME / "problems.jsonl"
_SIDECAR = _CORPUS / _STAGING_NAME / "_provenance.json"
_DOC = _ROOT / "docs" / "architecture" / "problem_bank_variant_intake_pb20.md"

_PATHLIKE = re.compile(r"^[\w./*\[\]{}\-]+$")
# 노출 글롭을 가진 소스 트리 — 학생 노출·측정·변이 도구가 모두 여기 산다.
_SCAN_TREES = ("src", "scripts")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _corpus_glob_constants() -> dict[str, set[str]]:
    """소스·스크립트의 `problem_bank` 글롭 상수 → 그것을 가진 파일들(레포 루트 상대).

    경로형 상수(공백 없음)만 본다 — docstring 산문 속 예시를 글롭으로 오인하지 않는다.
    """
    found: dict[str, set[str]] = {}
    for tree_name in _SCAN_TREES:
        for path in (_ROOT / tree_name).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            rel = path.relative_to(_ROOT).as_posix()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and _PATHLIKE.match(node.value)
                    and "problem_bank" in node.value
                    and "*" in node.value
                ):
                    found.setdefault(node.value, set()).add(rel)
    return found


def _dir_segment(pattern: str) -> str:
    """글롭 상수에서 디렉터리 글롭 구간(`problem_bank` + `*`를 가진 구간)만 뽑는다."""
    for segment in pattern.split("/"):
        if "problem_bank" in segment and "*" in segment:
            return segment
    raise AssertionError(f"디렉터리 글롭 구간을 못 찾았다: {pattern}")


# ── ① 로트 동결 ────────────────────────────────────────────────────────────────


def test_staged_lot_matches_its_sidecar() -> None:
    sidecar = json.loads(_SIDECAR.read_text(encoding="utf-8"))
    raw = _STAGING.read_bytes()
    rows = _rows(_STAGING)
    assert sidecar["record_count"] == len(rows) > 0
    assert sidecar["sha256"] == hashlib.sha256(raw).hexdigest(), (
        "스테이징 로트가 사이드카 sha256과 다르다 — 파일이 바뀌면 이전 감사 라벨은 다른 로트의 것이다. "
        "의도한 재생성이면 사이드카 sha256·record_count를 함께 갱신하고 감사를 다시 받는다."
    )
    assert sidecar["staging"]["status"] == "staged_not_exposed"


# ── ② 노출 글롭 밖 ─────────────────────────────────────────────────────────────


def test_no_exposure_glob_matches_the_staging_directory() -> None:
    constants = _corpus_glob_constants()
    segments = {_dir_segment(c) for c in constants}
    # 스캔 0건은 실패다 — 기존 소비처가 최소한 `problem_bank_*`·`problem_bank*` 두 형태로 실재한다.
    assert {"problem_bank_*", "problem_bank*"} <= segments, segments
    assert sum(len(files) for files in constants.values()) >= 20
    for segment in sorted(segments):
        assert not fnmatch.fnmatch(_STAGING_NAME, segment), (
            f"글롭 {segment!r}가 스테이징 디렉터리 {_STAGING_NAME}와 일치한다 — "
            "검수 감사 전에 노출 경로가 이 로트를 읽게 된다"
        )
        # 양성 대조군: 같은 글롭이 실제 코퍼스 디렉터리에는 일치해야 스캐너가 의미 있다.
        assert fnmatch.fnmatch("problem_bank_generated_v0", segment), segment


def test_no_source_enumerates_every_corpus_directory_for_problem_rows() -> None:
    """`rglob("problems.jsonl")`·`glob("*/problems.jsonl")`처럼 디렉터리명에 묶이지 않는 읽기가 없다.

    그런 읽기가 하나라도 있으면 디렉터리명 격리(②)는 그 소비처에 대해 무의미하다.
    """
    offenders: list[str] = []
    seen_files = 0
    for tree_name in _SCAN_TREES:
        for path in (_ROOT / tree_name).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            seen_files += 1
            rel = path.relative_to(_ROOT).as_posix()
            for node in ast.walk(tree):
                # ⓐ `glob("…")`·`rglob("…")` 호출 인자로 직접 준 경우.
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"glob", "rglob"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and "problems.jsonl" in node.args[0].value
                    and "problem_bank" not in node.args[0].value
                ):
                    offenders.append(f"{rel}:{node.lineno} (glob 인자)")
                # ⓑ 상수로 선언해 두고 변수로 넘기는 경우 — 호출 인자만 보면 놓친다.
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and _PATHLIKE.match(node.value)
                    and "problems.jsonl" in node.value
                    and "*" in node.value
                    and "problem_bank" not in node.value
                ):
                    offenders.append(f"{rel}:{node.lineno} (글롭 상수 {node.value})")
    assert seen_files > 500, "소스 스캔이 공허하다"
    assert not offenders, f"디렉터리명에 묶이지 않는 problems.jsonl 열거: {offenders}"


def test_populate_discovery_does_not_return_the_staging_file() -> None:
    discovered = discover_problem_corpora(_ROOT)
    names = {p.parent.name for p in discovered}
    assert len(discovered) >= 30, "코퍼스 발견이 공허하다 — 스캔 0건에 가깝다"
    assert "problem_bank_generated_v0" in names  # 양성 대조군
    assert _STAGING_NAME not in names


def test_staged_slugs_are_disjoint_from_every_exposed_corpus() -> None:
    """같은 slug가 양쪽에 있으면 승격 시 upsert 충돌(내용 덮어쓰기)이다."""
    staged = {r["slug"] for r in _rows(_STAGING)}
    exposed: set[str] = set()
    for path in discover_problem_corpora(_ROOT):
        exposed.update(r["slug"] for r in _rows(path))
    assert len(exposed) > 10_000 and staged
    assert staged.isdisjoint(exposed)


# ── ③ 서빙 게이트 ──────────────────────────────────────────────────────────────


def test_staged_rows_are_unreviewed_and_unpublished() -> None:
    rows = _rows(_STAGING)
    assert all(not r.get("review_status") for r in rows), "검수 공백이 아닌 행 — 감사 없는 각인이다"
    assert all(r.get("is_published") is False for r in rows)


def test_serving_review_predicate_rejects_every_staged_row() -> None:
    records = load_problem_bank_records(_STAGING)
    assert len(records) == len(_rows(_STAGING)) > 0
    assert not any(is_review_cleared(rec.problem) for rec in records)
    # 대조군: 같은 술어가 approved는 통과시킨다 — 항상 False인 술어는 위 단언을 공허하게 만든다.
    approved = records[0].problem.model_copy(update={"review_status": ReviewStatus.approved})
    assert is_review_cleared(approved) is True
    assert is_review_status_cleared(None) is False


def test_staged_rows_have_no_distractor_map_so_probe_candidates_stay_inert() -> None:
    """진단 프로브 후보 조회는 검수 게이트가 없고 `distractor_map` 보유 행만 읽는다(조사 문서 §1.2).

    그래서 변형 행이 그 조회에 닿지 않는 이유는 게이트가 아니라 *이 필드의 부재*다 — 부재를 동결한다.
    누군가 변형에 distractor_map을 달면 이 테스트가 RED가 되어 프로브 경로의 검수 공백을 다시 판정하게 한다.
    """
    assert all(row.get("distractor_map") is None for row in _rows(_STAGING))
    # 양성 대조군: 필드는 실재하는 개념이다(선지형 코퍼스는 보유) — 항상 None인 필드가 아니다.
    mc_rows = _rows(_CORPUS / "problem_bank_misconception_mc_v0" / "problems.jsonl")
    assert any(row.get("distractor_map") for row in mc_rows)


def test_cat_candidate_pool_requires_approved() -> None:
    """기본 CAT 후보 풀의 WHERE에 `review_status == approved` 항이 있다(허용목록)."""
    compiled = [c.compile(dialect=postgresql.dialect()) for c in candidate_pool_conditions()]
    review_terms = [c for c in compiled if "review_status" in str(c)]
    assert len(review_terms) == 1, [str(c) for c in compiled]
    params = list(review_terms[0].params.values())
    assert any(getattr(p, "value", p) == "approved" for p in params), params
    assert " IS DISTINCT FROM " not in str(review_terms[0])  # 격리 배제식(통과 허용)이 아니다


# ── ④ 승격 시 근거 차용 금지 ───────────────────────────────────────────────────


def test_staging_is_not_a_known_corpus_and_cannot_borrow_another_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 저장소 루트에서 실행한다 — 백필 CLI의 운영 호출 조건(Kiki 런북)이다. `corpus_backfill_refusal`은
    # 레포 코퍼스 디렉터리를 *상대경로*(`Path("data/corpus")`)로 들고 있어, CI 백엔드 잡의 cwd
    # (`src/backend`)에서는 같은 입력에 대해 거부 대신 None을 돌려준다(PB-20이 실측한 잠복 결함 —
    # 후속 태스크가 소유한다). 이 테스트는 그 결함을 덮지 않고 *유효한 호출 조건*만 고정한다.
    monkeypatch.chdir(_ROOT)
    kind, _ = classify_corpus(_STAGING)
    assert kind == "other"
    for borrowed in ("generated_v0", "rephrased_v0", "p3_calculus1_diff_v0"):
        refusal = corpus_backfill_refusal(_STAGING, borrowed)
        assert refusal is not None and "근거 차용" in refusal, borrowed


# ── ⑤ 로트 크기 사실 ───────────────────────────────────────────────────────────


def test_only_the_whole_lot_can_reach_the_audit_minimum() -> None:
    by_mode: dict[str, int] = {}
    for row in _rows(_STAGING):
        mode = row["slug"].split("-")[2]  # wm-var-{lad|cnd|inv}-…
        by_mode[mode] = by_mode.get(mode, 0) + 1
    assert set(by_mode) == {"lad", "cnd", "inv"}
    total = sum(by_mode.values())
    assert total >= _MIN_N, "로트 전체가 최소 표본에 못 미친다 — 이 코퍼스는 승격할 수 없다"
    assert all(n < _MIN_N for n in by_mode.values()), (
        f"모드 하나가 최소 표본({_MIN_N})에 도달했다({by_mode}) — 쪼개 감사하는 경로가 열렸다. "
        "문서 §4의 '로트는 하나' 결정을 다시 판정한다."
    )


# ── 행 불변식(PB-09 계약의 스테이징 재확인) ─────────────────────────────────────


def test_staged_rows_carry_exactly_one_parent_to_child_relation() -> None:
    generated_slugs = {
        r["slug"] for r in _rows(_CORPUS / "problem_bank_generated_v0" / "problems.jsonl")
    }
    structure = {"심화", "선수", "대조"}
    for row in _rows(_STAGING):
        (relation,) = row["relations"]
        assert relation["parent_slug"] in generated_slugs
        assert relation["parent_slug"] != row["slug"]
        assert relation["similarity_score"] is None
        expected = (
            "VARIANT_STRUCTURE" if relation["relation_type"] in structure else "VARIANT_CONTEXT"
        )
        assert row["generation_type"] == expected, row["slug"]


# ── 위생 감사가 스테이징을 본다 ─────────────────────────────────────────────────


def test_provenance_audit_covers_the_staging_directory() -> None:
    report = audit_corpus_root(_CORPUS)
    assert report.corpora_scanned >= 30
    assert not [v for v in report.violations if v.corpus == _STAGING_NAME], report.violations


# ── ⑥ 조사 문서의 소비처 목록 완전성 ───────────────────────────────────────────


def test_investigation_doc_names_every_glob_consumer() -> None:
    text = _DOC.read_text(encoding="utf-8")
    consumers = sorted({f for files in _corpus_glob_constants().values() for f in files})
    assert len(consumers) >= 20
    missing = [f for f in consumers if f not in text]
    assert not missing, (
        f"조사 문서에 분류되지 않은 글롭 소비처: {missing} — 새 소비처는 학생 노출 여부를 판정해 "
        "문서 표에 추가한 뒤에만 들어온다."
    )
