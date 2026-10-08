"""P3-03 미분 문항 은행 — 커밋된 은행의 불변식과 Phase 3 계측기 연결 가능성 — hermetic·생성 0.

생성기를 돌리지 않고 **커밋된 `problem_bank_p3_calculus1_diff_v0` 파일만** 읽는다(그래서 backend 잡 상시
경로에서 돈다 — 생성기가 아닌 경로, 예컨대 은행 직접 편집으로도 계약이 깨지는 것을 잡는다).

핵심 축 — "approved만 빠진 상태"의 증명
---------------------------------------
이 은행은 `review_status` 키를 쓰지 않으므로 계측기(`phase3_coverage`)는 이 문항을 적격으로 세지
않는다(승인은 감사 표본 경로의 몫). 그러나 **승인만 되면** 일곱 개념(02-03·04·05·06·08·09·10)이
충족으로 세어져야 의미가 있다.
이를 실측하려고 임시 저장소 루트(코퍼스 디렉터리는 심볼릭 링크, 이 은행만 변형 복사본)를 만들어

  · 키 제거본(`review_status` 없음) → 일곱 개념 미충족 (현행 상태의 재현)
  · 전건 `approved` 본            → 일곱 개념 '스킬 연결된 적격 문항' 충족

을 둘 다 단언한다 — 한쪽만 보면 "항상 충족"이나 "항상 미충족"인 계측기와 구별되지 않는다.
Concept Completeness의 'solution' 연결(해설 + 풀이 단계 `verify.solution_steps`)도 같은 방식으로
보고, 승인본에서 단계만 지운 대조군이 다시 missing임을 함께 단언한다.
레포 파일은 바꾸지 않는다(변형은 전부 tmp). 이 테스트가 *레포 파일의 승인 여부*에 의존하지 않도록
두 변형 모두 `review_status`를 명시적으로 덮어쓴다(감사 승인이 나중에 레포 은행에 들어와도 안 깨진다).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.p3_calculus1_diff_batch import CORPUS_DIR_NAME
from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards.phase3_scope import (
    default_spec_path,
    load_reference_index,
    load_scope_spec,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, skeleton_of
from whymath_backend.ops import provenance_audit as pa

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS = _REPO_ROOT / "data" / "corpus"
_BANK = _CORPUS / CORPUS_DIR_NAME
_CODES = (
    "[12미적Ⅰ-02-03]",
    "[12미적Ⅰ-02-04]",
    "[12미적Ⅰ-02-05]",
    "[12미적Ⅰ-02-06]",
    "[12미적Ⅰ-02-08]",
    "[12미적Ⅰ-02-09]",
    "[12미적Ⅰ-02-10]",
)
#: 오개념 유발 슬롯의 오답 귀속 id. 02-06은 핵심 오개념 M0674에 kebab 좌석이 없어 M-id를 그대로 쓴다(전용
#: 테스트 `test_kebab_seat_absence_is_a_tripwire`가 좌석 출현을 신호한다). 02-09는 5회차 은행 감사(2026-10-08)
#: 처분으로 핵심 M0677(설명 손상·절차 미기술 — 원문 정정 QUAL-14)에서 **M0615**('고차방정식의 근을 차수만큼으로
#: 단정' · [10공수1-02-07])로 옮겼다 — 차수로 센 값의 선지만 연결한다.
_KEBAB_OF = {
    "[12미적Ⅰ-02-03]": "power-rule-step-omitted",
    "[12미적Ⅰ-02-04]": "product-rule-naive",
    "[12미적Ⅰ-02-05]": "power-rule-step-omitted",
    "[12미적Ⅰ-02-06]": "M0674",
    "[12미적Ⅰ-02-08]": "critical-point-implies-extremum",
    "[12미적Ⅰ-02-09]": "M0615",
    "[12미적Ⅰ-02-10]": "power-rule-step-omitted",
}
#: 승인돼도 *핵심 오개념 사슬*이 0인 개념 — 핵심 M-id(M0673·M0676·M0678)가 크로스링크로 닿지 않거나
#: (MISC-40 미승격) 02-06은 distractor가 계측기의 사슬 정의에 안 걸린다. stale 가드: 사슬이 생기면 red.
#: 02-09(5회차 감사 2026-10-08 추가): 오답 선지를 핵심 M0677에서 M0615로 옮겨 사슬이 끊겼다 — M0615는 명세의
#: 핵심 오개념이 아니다. 종전 사슬은 설명이 손상된(절차 미기술) M0677 연결이 만든 것이었다(판정자 지적 12건).
#: QUAL-14가 M0677 원문을 정정해 절차가 적히면 다시 연결할 수 있다(그때 이 항목을 지운다).
_CHAIN_UNREACHED = frozenset(
    {
        "[12미적Ⅰ-02-05]",
        "[12미적Ⅰ-02-06]",
        "[12미적Ⅰ-02-08]",
        "[12미적Ⅰ-02-09]",
        "[12미적Ⅰ-02-10]",
    }
)


def _rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (_BANK / "problems.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_committed_bank_shape_per_concept_and_slot() -> None:
    rows = _rows()
    for code in _CODES:
        mine = [r for r in rows if r["achievement_standard_codes"] == [code]]
        assert len(mine) >= len(SLOT_IDS)  # 6슬롯 모두 최소 1건(명세 슬롯당 최소 고유 문항 1)
        for slot in SLOT_IDS:
            in_slot = [r for r in mine if r["tags"] == [f"p3-slot:{slot}"]]
            assert in_slot, f"{code} 슬롯 {slot}: 0건"
        # 개념당 고유 문면 골격 30 이상(명세 distinct_basis 정의)
        assert len({skeleton_of(str(r["question_text"])) for r in mine}) >= 30


def test_committed_bank_never_carries_review_status_and_stays_unpublished() -> None:
    for row in _rows():
        assert "review_status" not in row, row["slug"]
        assert row["is_published"] is False
        assert row["license"] == "WHYMATH_GENERATED"
        assert row["source_type"] == "자체생성"
        assert row["verify"]["verification_tier"] == "machine_sampled"  # type: ignore[index]


def test_misconception_trigger_rows_carry_the_catalogued_kebab_only() -> None:
    rows = _rows()
    for code, kebab in _KEBAB_OF.items():
        trigger = [
            r
            for r in rows
            if r["achievement_standard_codes"] == [code]
            and r["tags"] == ["p3-slot:misconception_trigger"]
        ]
        assert trigger
        for row in trigger:
            assert row["question_format"] == "객관식"
            assert {d["misconception_id"] for d in row["distractor_map"]} == {kebab}  # type: ignore[attr-defined,union-attr]
        others = [r for r in rows if r["achievement_standard_codes"] == [code] and r not in trigger]
        assert all("distractor_map" not in r for r in others)


def test_sidecar_passes_the_provenance_audit(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    (root / CORPUS_DIR_NAME).mkdir(parents=True)
    for name in ("problems.jsonl", "_provenance.json"):
        (root / CORPUS_DIR_NAME / name).write_bytes((_BANK / name).read_bytes())
    report = pa.audit_corpus_root(root)
    assert report.exit_code == 0, [v for v in report.violations]


def _tmp_root(tmp_path: Path, *, approved: bool, strip_steps: bool = False) -> Path:
    """데이터 코퍼스를 링크로 잇고 이 은행만 `review_status`를 명시적으로 덮어쓴 복사본으로 둔다.

    `strip_steps`면 복사본에서 `verify.solution_steps`를 지운다(계측기 'solution' 연결의 변별력 대조군).
    """
    name = ("approved" if approved else "unreviewed") + ("_nosteps" if strip_steps else "")
    root = tmp_path / name
    (root / "data" / "corpus").mkdir(parents=True)
    for entry in _CORPUS.iterdir():
        if entry.name != CORPUS_DIR_NAME:
            (root / "data" / "corpus" / entry.name).symlink_to(entry)
    bank = root / "data" / "corpus" / CORPUS_DIR_NAME
    bank.mkdir()
    with (bank / "problems.jsonl").open("w", encoding="utf-8") as fh:
        for row in _rows():
            row.pop("review_status", None)
            if approved:
                row["review_status"] = "approved"
            if strip_steps:
                row["verify"].pop("solution_steps", None)  # type: ignore[union-attr]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return root


def _facts_for(root: Path) -> dict[str, pc.ConceptFacts]:
    spec = load_scope_spec(default_spec_path())
    index = load_reference_index(spec)
    corpus = pc.load_corpus(spec, root)
    return {c.code: pc._facts(spec, index, corpus, c) for c in spec.concepts if c.code in _CODES}


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_only_approval_is_missing_for_the_seven_concepts(tmp_path: Path) -> None:
    unreviewed = _facts_for(_tmp_root(tmp_path, approved=False))
    approved = _facts_for(_tmp_root(tmp_path, approved=True))
    for code in _CODES:
        # 미승인 — 계측기는 적격으로 세지 않는다(현행 상태).
        assert unreviewed[code].eligible == ()
        assert unreviewed[code].skill_linked == ()
        # 승인만 되면 — 스킬 연결 문항이 생기고(개념 스킬 ∩ 문항 유형 스킬) 핵심 오개념까지 닿는다.
        assert approved[code].eligible, code
        assert approved[code].skill_linked, f"{code}: 승인돼도 스킬 연결 0 — 문제유형→스킬 단절"
        if code in _CHAIN_UNREACHED:
            assert not approved[
                code
            ].chain_problems, f"{code}: 사슬이 생겼다 — _CHAIN_UNREACHED 삭제"
        else:
            assert approved[code].chain_problems, f"{code}: 핵심 오개념 사슬 0"
        assert approved[code].core_misconceptions  # 명세 핵심 오개념이 코퍼스에 실재
        assert approved[code].content_present  # 개념 콘텐츠 행 존재(완전 연결 조건 1)
        assert pc._is_fully_linked(approved[code])
        assert not pc._is_fully_linked(unreviewed[code])


def _solution_status(root: Path) -> dict[str, str]:
    """개념별 Concept Completeness 'solution' 연결 상태(linked/missing) — 계측기 정의 그대로."""
    spec = load_scope_spec(default_spec_path())
    index = load_reference_index(spec)
    corpus = pc.load_corpus(spec, root)
    return {
        c.code: pc._completeness_links(pc._facts(spec, index, corpus, c), corpus)["solution"][0]
        for c in spec.concepts
    }


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_solution_link_needs_only_approval_and_is_made_by_the_steps(tmp_path: Path) -> None:
    """'solution' 연결 = 적격(승인) 문항 중 해설과 비어 있지 않은 `solution_steps`가 둘 다 있는 문항.

    · 키 제거본 → 일곱 개념 missing(승인 0 — 현행 상태의 재현).
    · 전건 approved 본 → 일곱 개념 linked(풀이 단계 도입 효과 — 2026-10-07 실측 계측기 전체 2/10 →
      9/10. 남은 [12미적Ⅰ-02-02]은 다른 은행 소관이라 이 테스트가 단언하지 않는다).
    · approved 본에서 단계만 지운 대조군 → 일곱 개념 다시 missing — 연결을 만든 것이 해설이 아니라
      단계임을 보인다(한쪽만 보면 '항상 linked'인 계측기와 구별되지 않는다).
    """
    unreviewed = _solution_status(_tmp_root(tmp_path, approved=False))
    approved = _solution_status(_tmp_root(tmp_path, approved=True))
    stripped = _solution_status(_tmp_root(tmp_path, approved=True, strip_steps=True))
    for code in _CODES:
        assert unreviewed[code] == "missing", code
        assert approved[code] == "linked", code
        assert stripped[code] == "missing", code
    linked = {code for code, status in approved.items() if status == "linked"}
    assert linked - {c for c, s in unreviewed.items() if s == "linked"} == set(_CODES)


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="data/corpus 부재")
def test_content_coverage_rises_by_exactly_the_seven_concepts_when_approved(tmp_path: Path) -> None:
    """지표 단위 대조 — 승인 본은 키 제거 본보다 Content Coverage 충족 개념이 정확히 7개 많다."""
    spec = load_scope_spec(default_spec_path())
    index = load_reference_index(spec)
    met = {}
    for approved in (False, True):
        root = _tmp_root(tmp_path, approved=approved)
        report = pc.evaluate(spec, index, pc.load_corpus(spec, root))
        met[approved] = {u.subject for u in report.metric("content_coverage_rate").unmet}
    assert met[False] - met[True] == set(_CODES)
