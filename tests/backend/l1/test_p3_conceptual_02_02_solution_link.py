"""P3-31 — [12미적Ⅰ-02-02] 해설 연결: 커밋된 conceptual_v0 의 불변식과 계측기 연결 — hermetic·생성 0.

배경: Phase 3 계측기(`l1/standards/phase3_coverage`)의 Concept Completeness 'solution' 연결은 적격
(승인) 문항 중 **해설과 비어 있지 않은 `verify.solution_steps` 가 둘 다 있는** 문항이 하나라도 있으면 선다.
[12미적Ⅰ-02-02] 의 승인 문항 24건(`problem_bank_conceptual_v0`)은 해설은 있고 단계만 없었다.

해법 선택 — 기존 24건에 단계를 더한다(생성 쪽 해법 '(가) 새 문항 은행'을 택하지 않은 이유는 태스크
P3-31 notes). 이때 승인 근거(코퍼스 표본 감사 200/360)가 새 내용으로 옮겨 가지 않는다는 문제를 이렇게 푼다:

  · 더해진 것은 `verify.solution_steps` **하나**뿐이다 — 감사가 본 내용(발문·선지·정답·해설·오답 귀속·
    검산 조건)은 바이트가 같다. 아래 `test_audited_content_is_unchanged_under_the_approval` 이 감사 시점
    내용의 지문을 핀으로 박아 둔다(핀을 만든 값은 단계를 더하기 **전** 코퍼스에서 산출).
  · 새로 생긴 단계는 감사 표본이 아니라 **기계 증명 전수**로 덮는다 — 24건 전부가 Tier2
    (`verify_solution`)에서 전이 전건 correct 다(`test_every_step_chain_is_verified_correct_by_tier2`).
    표본 감사의 보증이 닿지 않는 내용은 표본으로 덮은 척하지 않는다.

이 테스트는 생성기를 돌리지 않고 커밋된 파일만 읽는다(그래서 backend 잡 상시 경로에서 돈다).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards.phase3_scope import (
    default_spec_path,
    load_reference_index,
    load_scope_spec,
)
from whymath_backend.l3.verify_solution import verify_solution

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus"
_BANK_NAME = "problem_bank_conceptual_v0"
_BANK = _CORPUS / _BANK_NAME
_CODE = "[12미적Ⅰ-02-02]"
_SRC_ID = "H:12미적Ⅰ02-02"

#: 감사(코퍼스 표본 200/360 · 결함 0)가 본 문항 내용의 필드. 풀이 단계는 감사 뒤에 더해졌으므로 제외한다.
_AUDITED_FIELDS = (
    "question_text",
    "choices",
    "answer",
    "answer_explanation",
    "distractor_map",
    "achievement_standard_codes",
    "concepts",
)

#: 단계를 더하기 **전** 코퍼스에서 산출한 감사 시점 내용 지문(24건·id 정렬). 내용이 한 글자라도 바뀌면 깨진다.
_AUDITED_CONTENT_DIGEST = "9e787871c515e547f0eb03d9b1026abb914f753791c7755614c394121a09af53"


def _rows() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (_BANK / "problems.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _targets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[12미적Ⅰ-02-02] 를 PRIMARY 로 삼는 문항(계측기가 적격 판정에 쓰는 정의 그대로)."""
    return [
        r
        for r in rows
        if any(
            isinstance(t, dict)
            and t.get("role") == "PRIMARY"
            and t.get("concept_src_id") == _SRC_ID
            for t in r.get("concepts") or []
        )
    ]


def _audited_content_digest(rows: list[dict[str, Any]]) -> str:
    per_row = []
    for r in rows:
        body = {k: r[k] for k in _AUDITED_FIELDS}
        body["verify"] = {k: v for k, v in r["verify"].items() if k != "solution_steps"}
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        per_row.append(f"{r['problem_id']}:{hashlib.sha256(canonical.encode()).hexdigest()}")
    return hashlib.sha256("\n".join(sorted(per_row)).encode()).hexdigest()


def test_target_rows_are_the_24_approved_differentiability_items() -> None:
    rows = _targets(_rows())
    assert len(rows) == 24
    assert {r["review_status"] for r in rows} == {"approved"}
    assert {r["verify"]["answer_kind"] for r in rows} == {"is_differentiable"}


def test_every_target_row_has_explanation_and_steps() -> None:
    for r in _targets(_rows()):
        steps = r["verify"].get("solution_steps")
        assert isinstance(steps, list) and len(steps) >= 2, r["problem_id"]
        assert all(isinstance(s, str) and s.strip() for s in steps)
        assert r["answer_explanation"].strip()


def test_every_step_chain_is_verified_correct_by_tier2() -> None:
    """단계는 표본이 아니라 전수 기계 증명으로 덮는다 — 전이 전건 correct(미판정도 0)."""
    for r in _targets(_rows()):
        steps = r["verify"]["solution_steps"]
        result = verify_solution(steps)
        assert result.n_transitions == len(steps) - 1, r["problem_id"]
        assert result.n_correct == result.n_transitions, r["problem_id"]
        assert not result.has_incorrect


def test_audited_content_is_unchanged_under_the_approval() -> None:
    """승인이 인증한 내용(풀이 단계 제외)이 감사 시점과 같다 — 승인이 새 내용으로 옮겨 가지 않는다."""
    assert _audited_content_digest(_targets(_rows())) == _AUDITED_CONTENT_DIGEST


def test_binding_detects_a_content_change_under_an_intact_approval_stamp() -> None:
    """대조군 — 승인 각인은 그대로 두고 해설을 1글자 바꾸면 지문이 달라진다(핀이 변별력을 갖는다)."""
    rows = _targets(_rows())
    assert _audited_content_digest(rows) == _AUDITED_CONTENT_DIGEST  # 원본은 일치
    rows[0] = {**rows[0], "answer_explanation": rows[0]["answer_explanation"] + "."}
    assert _audited_content_digest(rows) != _AUDITED_CONTENT_DIGEST


def test_other_corpus_rows_carry_no_steps_added_by_this_change() -> None:
    """이번 변경은 [12미적Ⅰ-02-02] 24건에만 닿는다 — 같은 코퍼스의 나머지 348건은 단계가 없는 그대로다.

    336 → 348: P3-51 이 극값의 개수 양성 예 12건을 더했다(이 문항들도 풀이 단계가 없다).
    """
    rows = _rows()
    target_ids = {r["problem_id"] for r in _targets(rows)}
    others = [r for r in rows if r["problem_id"] not in target_ids]
    assert len(others) == 348
    assert not [r for r in others if r["verify"].get("solution_steps")]


def _solution_status(root: Path) -> dict[str, str]:
    """개념별 Concept Completeness 'solution' 연결 상태 — 계측기 정의 그대로."""
    spec = load_scope_spec(default_spec_path())
    index = load_reference_index(spec)
    corpus = pc.load_corpus(spec, root)
    return {
        c.code: pc._completeness_links(pc._facts(spec, index, corpus, c), corpus)["solution"][0]
        for c in spec.concepts
    }


def _tmp_root(tmp_path: Path, *, strip_steps: bool) -> Path:
    """데이터 코퍼스를 링크로 잇고 conceptual_v0 만 (단계를 지운) 복사본으로 둔다 — 레포 파일은 안 바꾼다."""
    root = tmp_path / ("nosteps" if strip_steps else "committed")
    (root / "data" / "corpus").mkdir(parents=True)
    for entry in _CORPUS.iterdir():
        # P3-05 빈 칸 채우기 은행(승인)도 02-02 문항을 더하므로, 이 은행 하나의 효과를 보려면 뺀다.
        if entry.name not in (_BANK_NAME, "problem_bank_p3_fill_v0"):
            (root / "data" / "corpus" / entry.name).symlink_to(entry)
    bank = root / "data" / "corpus" / _BANK_NAME
    bank.mkdir()
    with (bank / "problems.jsonl").open("w", encoding="utf-8") as fh:
        for row in _rows():
            if strip_steps:
                row["verify"].pop("solution_steps", None)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return root


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_solution_link_of_02_02_is_made_by_the_steps(tmp_path: Path) -> None:
    """커밋 상태는 linked, 단계만 지운 대조군은 missing — 연결을 만든 것이 이번 변경(단계)임을 보인다."""
    committed = _solution_status(_tmp_root(tmp_path, strip_steps=False))
    stripped = _solution_status(_tmp_root(tmp_path, strip_steps=True))
    assert committed[_CODE] == "linked"
    assert stripped[_CODE] == "missing"
    # 다른 개념의 연결은 줄지 않는다(대조군에서도 같은 값 — 이번 변경은 02-02 외에 닿지 않는다).
    for code, status in committed.items():
        if code != _CODE:
            assert stripped[code] == status, code
    linked = {c for c, s in committed.items() if s == "linked"}
    assert _CODE in linked
