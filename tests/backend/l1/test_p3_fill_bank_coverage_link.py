"""P3-05 빈 칸 채우기 은행 — 커밋된 은행의 승인 결속과 Phase 3 계측기 연결 — hermetic·생성 0.

생성기를 돌리지 않고 **커밋된 `problem_bank_p3_fill_v0` 파일만** 읽는다(그래서 backend 잡 상시 경로에서
돈다 — 생성기가 아닌 경로, 예컨대 은행 직접 편집으로도 계약이 깨지는 것을 잡는다).

핵심 축 두 개
-------------
1. **승인은 감사받은 내용에만 붙는다.** 저장소 은행은 3회차 S5 감사(기계 0 · 판정자 A 0 · B 0 → 결함
   0/204 · 보정 상한 0.01907 ≤ 0.02) 승인 뒤 코퍼스 단위 백필이 전건 `approved`를 각인한 상태이고,
   각인을 걷어 낸 바이트가 감사 동결 사본과 같아야 한다. 같은 방식의 P3-03 은행 결속
   (`test_p3_calculus1_diff_bank_coverage_link.py`)을 따른다.
2. **이 은행의 승인이 계측기를 움직인다.** 임시 저장소 루트(코퍼스 디렉터리는 심볼릭 링크, 이 은행만
   변형 복사본)를 만들어 `review_status`를 지운 본과 전건 `approved` 본을 둘 다 재서,

     · 승인 본 → Problem Coverage 8/8 · 6슬롯 60/60 (완료 판정 ⑤)
     · 미승인 본 → 두 스킬(규칙 일반화·문장제)이 비고 슬롯 칸 13개가 빈다

   를 함께 단언한다 — 한쪽만 보면 "항상 충족"이나 "항상 미충족"인 계측기와 구별되지 않는다. 레포 파일은
   바꾸지 않는다(변형은 전부 tmp, 두 변형 모두 `review_status`를 명시적으로 덮어쓴다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.p3_calculus1_diff_batch import strip_backfill_stamps
from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards.phase3_scope import (
    default_spec_path,
    load_reference_index,
    load_scope_spec,
)
from whymath_backend.ops import provenance_audit as pa

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus"
_BANK_NAME = "problem_bank_p3_fill_v0"
_BANK = _CORPUS / _BANK_NAME
#: 승인 근거가 된 감사 — 3회차 S5(자격 통과 프로토콜 · 결함 0/204 · 보정 상한 0.01907 ≤ 0.02).
_AUDITED_BANK = (
    _REPO_ROOT / "docs" / "data" / "p3_fill_audit" / "bank_audit_r3" / "audited_bank.jsonl"
)
#: 이 은행이 있어야 8/8이 되는 두 스킬(P3-05 설계 메모 §2) — 다른 어떤 코퍼스의 승인 문항도 행사하지 않는다.
_FILL_ONLY_SKILLS = ("skill.pattern-generalization", "skill.word-problem-modeling")


def _rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (_BANK / "problems.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_scan_is_not_vacuous() -> None:
    assert len(_rows()) == 204


def test_committed_bank_approval_is_bound_to_the_audited_content() -> None:
    """승인 각인은 감사받은 내용에만 붙는다 — 각인을 걷어 낸 바이트 == 3회차 감사 동결 사본.

    생성기를 고쳐 내용이 바뀌면(문항 1글자라도) 각인이 남아 있어도 여기서 빨개진다. 그때는 새 회차
    감사를 거쳐 이 경로·근거를 함께 바꿔야 한다 — 감사 없이 승인을 새 내용으로 옮기지 않는다.
    """
    committed = (_BANK / "problems.jsonl").read_text(encoding="utf-8")
    assert strip_backfill_stamps(committed).encode("utf-8") == _AUDITED_BANK.read_bytes()
    assert {row.get("review_status") for row in _rows()} == {"approved"}


def test_binding_detects_content_change_under_an_intact_stamp() -> None:
    """**변별력** — 각인을 그대로 두고 문항 내용만 1글자 바꾸면 결속이 깨진다(대조군: 원본은 성립)."""
    committed = (_BANK / "problems.jsonl").read_text(encoding="utf-8")
    first, rest = committed.split("\n", 1)
    row = json.loads(first)
    row["answer_explanation"] = str(row["answer_explanation"]) + " "
    tampered = json.dumps(row, ensure_ascii=False) + "\n" + rest
    assert tampered != committed  # 주입이 실제로 적용됐다
    assert row["review_status"] == "approved"  # 각인은 그대로
    assert strip_backfill_stamps(tampered).encode("utf-8") != _AUDITED_BANK.read_bytes()
    assert strip_backfill_stamps(committed).encode("utf-8") == _AUDITED_BANK.read_bytes()


def test_committed_bank_stays_unpublished_and_self_authored() -> None:
    for row in _rows():
        assert row["is_published"] is False
        assert row["license"] == "WHYMATH_GENERATED"
        assert row["source_type"] == "자체생성"
        assert row["verify"]["verification_tier"] == "machine_sampled"  # type: ignore[index]


def test_sidecar_passes_the_provenance_audit(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / _BANK_NAME).mkdir(parents=True)
    for name in ("problems.jsonl", "_provenance.json"):
        (root / _BANK_NAME / name).write_bytes((_BANK / name).read_bytes())
    report = pa.audit_corpus_root(root)
    assert report.exit_code == 0, [v for v in report.violations]


def _tmp_root(tmp_path: Path, *, approved: bool) -> Path:
    """데이터 코퍼스를 링크로 잇고 이 은행만 `review_status`를 명시적으로 덮어쓴 복사본으로 둔다."""
    root = tmp_path / ("approved" if approved else "unreviewed")
    (root / "data" / "corpus").mkdir(parents=True)
    for entry in _CORPUS.iterdir():
        if entry.name != _BANK_NAME:
            (root / "data" / "corpus" / entry.name).symlink_to(entry)
    bank = root / "data" / "corpus" / _BANK_NAME
    bank.mkdir()
    with (bank / "problems.jsonl").open("w", encoding="utf-8") as fh:
        for row in _rows():
            row.pop("review_status", None)
            if approved:
                row["review_status"] = "approved"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return root


def _skill_counts(root: Path) -> dict[str, int]:
    """승인 문항이 문제유형을 거쳐 행사하는 스킬별 건수 — `ops.phase3_metrics`의 ③과 같은 정의."""
    spec = load_scope_spec(default_spec_path())
    corpus = pc.load_corpus(spec, root)
    counts = {skill: 0 for skill in spec.skills}
    for problem in corpus.problems:
        if problem.review_status != pc.PROBLEM_ELIGIBLE_STATUS:
            continue
        skills: set[str] = set()
        for code in problem.problem_type_codes:
            skills.update(corpus.type_skills.get(code, ()))
        for skill in skills & set(counts):
            counts[skill] += 1
    return counts


def _unmet_slot_cells(root: Path) -> int:
    spec = load_scope_spec(default_spec_path())
    index = load_reference_index(spec)
    report = pc.evaluate(spec, index, pc.load_corpus(spec, root))
    assert report.slots is not None
    return sum(len(u.missing) for u in report.slots.unmet)


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_approval_of_this_bank_is_what_completes_problem_coverage(tmp_path: Path) -> None:
    """승인 본은 8/8 스킬을 행사하고, 미승인 본은 규칙 일반화·문장제 두 스킬이 0건이다."""
    approved = _skill_counts(_tmp_root(tmp_path, approved=True))
    unreviewed = _skill_counts(_tmp_root(tmp_path, approved=False))
    assert all(count > 0 for count in approved.values()), approved
    assert len(approved) == 8
    for skill in _FILL_ONLY_SKILLS:
        assert (
            unreviewed[skill] == 0
        ), f"{skill}: 이 은행이 없어도 이미 승인 문항이 있다 — 근거 소실"
        assert approved[skill] >= 24, f"{skill}: 승인 본에서 24건 미만"


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_approval_of_this_bank_is_what_fills_the_six_slots(tmp_path: Path) -> None:
    """승인 본은 핵심 개념 6슬롯 60칸을 전부 채우고, 미승인 본은 이 은행이 채운 13칸이 빈다."""
    assert _unmet_slot_cells(_tmp_root(tmp_path, approved=True)) == 0
    assert _unmet_slot_cells(_tmp_root(tmp_path, approved=False)) >= 13
