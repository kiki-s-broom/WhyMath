"""개념 평가 재료 참조 인덱스 빌더 — 자격 필터·매칭·전후 성공률·산출물.

핵심 회귀는 **측정의 변별력**이다. "주입 후 N%"만 재는 리포트는 주입이 아무 일도 하지 않아도
같은 숫자를 낼 수 있다(2026-07-17 logconfig 사고의 일반형). 그래서 여기서는 주입 *전* 0%를 실제로
재현한 뒤 후를 재고, 두 값이 다르다는 것 자체를 검사한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import concept_assessment_index as cai
from whymath_backend.harness.concept_assessment_index import (
    AXIS_CONCEPT_SRC_ID,
    AXIS_STANDARD_CODE,
    DROP_EMPTY_ANSWER_MAP,
    DROP_NOT_OWN_LICENSE,
    DROP_NOT_REVIEW_CLEARED,
    DROP_REVERIFY_NOT_PASS,
    DROP_TIER1_NOT_PASS,
    ConceptRow,
    build_report,
    discover_problem_files,
    eligible_problem_refs,
    index_payload,
    load_concepts,
    main,
    match_entries,
    render_rates,
    render_report,
)
from whymath_backend.schema.enums import is_review_status_cleared

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)


def _problem(**overrides: object) -> dict[str, object]:
    """상속 자격을 *모두* 갖춘 최소 문항 — 각 테스트는 한 축만 깨서 필터를 검사한다."""
    record: dict[str, object] = {
        "slug": "wm-test-1",
        "source_type": "자체생성",
        "license": "WHYMATH_GENERATED",
        # CONT-01 — 검수 축(fail-closed)이 붙어 자격 최소셋에 approved가 포함된다. 이 줄을 빼면
        # `review_status=None`이 되어 전 테스트가 탈락한다(게이트가 살아 있다는 방증이기도 하다).
        "review_status": "approved",
        "question_text": "x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오.",
        "answer": "3",
        "unit_codes": ["QUAD-EQ"],
        "achievement_standard_codes": ["[10공수1-02-02]"],
        "concepts": [{"concept_src_id": "HK06", "role": "PRIMARY"}],
        "difficulty_overall": 2.0,
        "verify": {"conditions": "x**2 - 5*x + 6 = 0", "answer_map": {"x": "3"}},
    }
    record.update(overrides)
    return record


def _write_bank(
    tmp_path: Path, records: list[dict[str, object]], name: str = "problem_bank_t"
) -> Path:
    bank = tmp_path / name
    bank.mkdir(parents=True, exist_ok=True)
    (bank / "problems.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    return tmp_path


def _concept(**overrides: object) -> ConceptRow:
    payload: dict[str, object] = {
        "code": "HK06",
        "name": "이차방정식의 풀이",
        "subject": "공통수학1",
        "unit": "방정식과 부등식",
        "metaphor": "저울의 균형과 같다.",
        "misconception": "판별식을 무시한다.",
        "formal_definition_internal": "최고차항의 차수가 2인 방정식.",
        "accepted_expressions": "인수분해로 두 근을 구한다",
        "standard_codes": ("[10공수1-02-02]",),
    }
    payload.update(overrides)
    return ConceptRow(**payload)  # type: ignore[arg-type]


# ── 자격 필터(5겹) ────────────────────────────────────────────────


def test_all_drop_reasons_are_reported_even_when_zero(tmp_path: Path) -> None:
    """다섯 겹 전부가 0으로라도 리포트에 나온다 — "0건 걸렀다"와 "필터가 없다"를 구분한다."""
    root = _write_bank(tmp_path, [_problem()])
    refs, drops, scanned = eligible_problem_refs(discover_problem_files(root))
    assert scanned == 1 and len(refs) == 1
    assert set(drops) == {
        DROP_NOT_OWN_LICENSE,
        DROP_NOT_REVIEW_CLEARED,
        DROP_REVERIFY_NOT_PASS,
        DROP_EMPTY_ANSWER_MAP,
        DROP_TIER1_NOT_PASS,
    }
    assert all(count == 0 for count in drops.values())


@pytest.mark.parametrize(
    ("overrides", "expected_drop"),
    [
        ({"license": "EXTERNAL"}, DROP_NOT_OWN_LICENSE),
        ({"source_type": "평가원"}, DROP_NOT_OWN_LICENSE),
        # CONT-01 검수 축 — approved가 *아닌* 세 상태 전부 fail-closed로 탈락한다.
        ({"review_status": "pending"}, DROP_NOT_REVIEW_CLEARED),
        ({"review_status": "rejected"}, DROP_NOT_REVIEW_CLEARED),
        ({"review_status": None}, DROP_NOT_REVIEW_CLEARED),
        ({"review_status": ""}, DROP_NOT_REVIEW_CLEARED),
        ({"review_status": "approved "}, DROP_NOT_REVIEW_CLEARED),
        (
            # 개념형(실근 *개수*) 문항 — 재검증은 통과하지만 answer_map이 비어 있어
            # `ConceptAssessment`를 만들 수 없다(빈 검증의 통과 위장 금지).
            {
                "verify": {
                    "conditions": "x**2 + 1 = 0",
                    "answer_map": {},
                    "answer_kind": "real_root_count",
                },
                "answer": "0",
            },
            DROP_EMPTY_ANSWER_MAP,
        ),
        (
            # 답이 조건을 만족하지 않는다 → 재검증 자체가 fail로 걸린다(오염 차단).
            {"verify": {"conditions": "x**2 - 5*x + 6 = 0", "answer_map": {"x": "7"}}},
            DROP_REVERIFY_NOT_PASS,
        ),
        (
            # 근 집계(Vieta) 문항 — 답이 근이 아니라 근들의 합이라 Tier1 대입은 실패한다.
            {
                "verify": {
                    "conditions": "x**2 - 5*x + 6 = 0",
                    "answer_map": {"x": "5"},
                    "answer_aggregate": "sum",
                },
                "answer": "5",
            },
            DROP_TIER1_NOT_PASS,
        ),
    ],
)
def test_each_filter_layer_actually_drops(
    tmp_path: Path, overrides: dict[str, object], expected_drop: str
) -> None:
    """각 겹이 *실제로* 탈락시킨다 — 통과만 확인하는 검사는 필터의 존재를 증명하지 못한다."""
    root = _write_bank(tmp_path, [_problem(**overrides)])
    refs, drops, _ = eligible_problem_refs(discover_problem_files(root))
    assert refs == []
    assert drops[expected_drop] == 1


def test_missing_review_status_key_is_failed_closed(tmp_path: Path) -> None:
    """`review_status` 키가 *아예 없는* 레코드도 탈락한다(키 부재를 통과로 위장하지 않는다)."""
    record = _problem()
    del record["review_status"]
    root = _write_bank(tmp_path, [record])
    refs, drops, _ = eligible_problem_refs(discover_problem_files(root))
    assert refs == []
    assert drops[DROP_NOT_REVIEW_CLEARED] == 1


def test_review_gate_discriminates_between_pending_and_approved(tmp_path: Path) -> None:
    """**변별력** — 같은 문항이 검수 상태 하나 차이로 통과/탈락이 갈린다(CONT-01 acceptance ④).

    성공·실패 양쪽을 *같은 어서션 축*으로 관측한다. 한쪽만 재면 "게이트가 아무 일도 안 해도 같은
    숫자"인 위장 검증이 된다(2026-07-17 logconfig 사고의 일반형). 두 관측이 서로 다르다는 것
    자체가 게이트가 살아 있다는 증거다.
    """
    approved_root = _write_bank(tmp_path / "ok", [_problem(review_status="approved")])
    pending_root = _write_bank(tmp_path / "ng", [_problem(review_status="pending")])

    ok_refs, ok_drops, ok_scanned = eligible_problem_refs(discover_problem_files(approved_root))
    ng_refs, ng_drops, ng_scanned = eligible_problem_refs(discover_problem_files(pending_root))

    # 두 입력의 스캔 건수는 같다 — 차이는 오직 검수 축에서만 난다(교란 변수 없음).
    assert ok_scanned == ng_scanned == 1
    # 정상 상태: 탈락하지 *않는다*.
    assert len(ok_refs) == 1
    assert ok_drops[DROP_NOT_REVIEW_CLEARED] == 0
    # 주입 상태: 실제로 탈락한다.
    assert ng_refs == []
    assert ng_drops[DROP_NOT_REVIEW_CLEARED] == 1
    # 다른 겹이 대신 걸러준 것이 아니다 — 검수 겹 외 사유는 양쪽 모두 0이어야 한다.
    assert all(v == 0 for k, v in ng_drops.items() if k != DROP_NOT_REVIEW_CLEARED)


def test_review_gate_drop_is_reported_in_payload_and_text(tmp_path: Path) -> None:
    """검수 탈락이 산출물(`filter_drops`)과 사람 리포트 양쪽에 남는다 — 관측 가능성."""
    root = _write_bank(
        tmp_path, [_problem(slug="ok"), _problem(slug="ng", review_status="pending")]
    )
    refs, drops, scanned = eligible_problem_refs(discover_problem_files(root))
    report = build_report([_concept()], refs, drops, scanned)
    payload = index_payload(report, concept_source="c.json")
    assert payload["filter_drops"][DROP_NOT_REVIEW_CLEARED] == 1
    # 값이 0인 겹도 키가 남는다(필터 소실이 산출물 diff에서 보이게).
    assert payload["filter_drops"][DROP_NOT_OWN_LICENSE] == 0
    assert DROP_NOT_REVIEW_CLEARED in render_report(report)


def test_review_gate_shares_authority_with_l6_runtime_gate() -> None:
    """빌드타임 필터와 L6 런타임 노출 게이트가 **같은 판정 함수**를 쓴다(기준 이원화 금지).

    문자열 리터럴을 각자 적으면 한쪽만 완화돼도 아무도 모른다. 두 경로가 같은 함수 객체를
    참조한다는 것을 여기서 동결한다.
    """
    from whymath_backend.l6 import _shared

    assert cai.is_review_status_cleared is is_review_status_cleared
    assert _shared.is_review_status_cleared is is_review_status_cleared
    # 그리고 그 공유 함수 자체가 fail-closed다 — 공유만 하고 기준이 느슨하면 의미가 없다.
    assert is_review_status_cleared("approved") is True
    assert is_review_status_cleared("pending") is False
    assert is_review_status_cleared(None) is False


# ── 매칭 ─────────────────────────────────────────────────────────


def test_direct_concept_code_beats_standard_code(tmp_path: Path) -> None:
    """개념 code 직결이 성취기준 다리보다 우선한다(더 강한 신호)."""
    root = _write_bank(
        tmp_path,
        [
            _problem(slug="via-standard", concepts=[], difficulty_overall=1.0),
            _problem(slug="via-code", achievement_standard_codes=[], difficulty_overall=5.0),
        ],
    )
    refs, _, _ = eligible_problem_refs(discover_problem_files(root))
    entries, uncovered = match_entries([_concept()], refs)
    assert uncovered == []
    assert entries[0].match_axis == AXIS_CONCEPT_SRC_ID
    assert entries[0].problem_slug == "via-code"


def test_easiest_candidate_wins_within_same_axis(tmp_path: Path) -> None:
    """같은 축이면 난이도가 낮은 문항을 고른다(문제 우선 제시의 정서 안전)."""
    root = _write_bank(
        tmp_path,
        [
            _problem(slug="hard", concepts=[], difficulty_overall=4.5),
            _problem(slug="easy", concepts=[], difficulty_overall=1.5),
        ],
    )
    refs, _, _ = eligible_problem_refs(discover_problem_files(root))
    entries, _ = match_entries([_concept()], refs)
    assert entries[0].match_axis == AXIS_STANDARD_CODE
    assert entries[0].problem_slug == "easy"


def test_uncovered_concepts_are_recorded_not_dropped(tmp_path: Path) -> None:
    """맞는 문항이 없는 개념은 *기록*된다 — 커버된 것만 세는 침묵 통과 금지."""
    root = _write_bank(tmp_path, [_problem()])
    refs, _, _ = eligible_problem_refs(discover_problem_files(root))
    entries, uncovered = match_entries(
        [_concept(), _concept(code="NO-MATCH", standard_codes=("[9수99-99]",))], refs
    )
    assert [e.concept_code for e in entries] == ["HK06"]
    assert uncovered == ["NO-MATCH"]


# ── 전/후 성공률(변별력) ──────────────────────────────────────────


def test_problem_based_rate_moves_from_zero_after_injection(tmp_path: Path) -> None:
    """주입 전 0% → 후 100%. 두 값이 같으면 측정이 무효라는 것을 이 대조가 드러낸다."""
    root = _write_bank(tmp_path, [_problem()])
    refs, _, _ = eligible_problem_refs(discover_problem_files(root))
    entries, _ = match_entries([_concept()], refs)
    before, after, dsl_invalid = render_rates([_concept()], entries)

    assert dsl_invalid == 0
    assert before["PROBLEM_BASED"].dsl_render_rate == pytest.approx(0.0)
    assert after["PROBLEM_BASED"].dsl_render_rate == pytest.approx(1.0)
    # 다른 어댑터는 원래 렌더되므로 주입이 값을 바꾸지 않는다(부작용 없음).
    assert before["SOCRATIC"].dsl_render_rate == after["SOCRATIC"].dsl_render_rate


def test_render_rates_use_supply_tally_breakdown(tmp_path: Path) -> None:
    """리포트가 `SupplyTally`를 소비한다 — 어댑터별 분해가 리포트 표면에 실제로 실린다."""
    root = _write_bank(tmp_path, [_problem()])
    refs, drops, scanned = eligible_problem_refs(discover_problem_files(root))
    report = build_report([_concept()], refs, drops, scanned)
    payload = report.to_json()
    assert payload["render_rate_after"]["PROBLEM_BASED"]["by_strategy"] == {
        "PROBLEM_BASED": {"dsl_render": 1}
    }
    assert payload["render_rate_before"]["PROBLEM_BASED"]["by_fallback_reason"] == {
        "CANNOT_RENDER": 1
    }
    assert "PROBLEM_BASED" in render_report(report)


# ── 산출물 ───────────────────────────────────────────────────────


def test_index_payload_is_deterministic_and_carries_uncovered(tmp_path: Path) -> None:
    """같은 입력 → 같은 바이트(시각 필드 없음) + 미커버 목록 보존."""
    root = _write_bank(tmp_path, [_problem()])
    refs, drops, scanned = eligible_problem_refs(discover_problem_files(root))
    concepts = [_concept(), _concept(code="NO-MATCH", standard_codes=("[9수99-99]",))]
    first = index_payload(build_report(concepts, refs, drops, scanned), concept_source="c.json")
    second = index_payload(build_report(concepts, refs, drops, scanned), concept_source="c.json")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["uncovered_concept_codes"] == ["NO-MATCH"]
    assert first["counts"]["concepts_uncovered"] == 1


def test_cli_writes_index_and_gate_fires_below_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI가 산출물을 쓰고, 임계 미달이면 exit 1(게이트가 실패 상태에서 실제로 실패한다)."""
    root = _write_bank(tmp_path, [_problem()])
    concepts_path = tmp_path / "content.json"
    concepts_path.write_text(
        json.dumps(
            {
                "content": [
                    {
                        "code": "HK06",
                        "name": "이차방정식의 풀이",
                        "subject": "공통수학1",
                        "metaphor": "저울의 균형과 같다.",
                        "standard_codes": ["[10공수1-02-02]"],
                        "review_status": "ai_estimated",
                    },
                    {
                        "code": "NO-MATCH",
                        "name": "미커버 개념",
                        "subject": "공통수학1",
                        "metaphor": "무엇에 빗댈 수 있다.",
                        "standard_codes": ["[9수99-99]"],
                        "review_status": "ai_estimated",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    argv = [
        "--corpus-root",
        str(root),
        "--concepts",
        str(concepts_path),
        "--out-dir",
        str(out_dir),
        "--write",
    ]
    assert main(argv) == 0
    written = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    assert [e["concept_code"] for e in written["entries"]] == ["HK06"]
    assert written["uncovered_concept_codes"] == ["NO-MATCH"]

    # 커버율 50%인 상태에서 하한 90%를 요구하면 게이트가 깨져야 한다.
    assert main([*argv, "--min-problem-based-rate", "0.9"]) == 1
    assert main([*argv, "--min-problem-based-rate", "0.4"]) == 0
    capsys.readouterr()


def test_cli_reports_input_error_without_pretending_success(tmp_path: Path) -> None:
    """입력 부재를 0건 통과로 위장하지 않는다(exit 2)."""
    assert main(["--corpus-root", str(tmp_path), "--concepts", str(tmp_path / "nope.json")]) == 2


# ── 실 코퍼스(배선 실재성) ────────────────────────────────────────


def test_shipped_concept_corpus_loads_with_review_status() -> None:
    """실 코퍼스 전 행(사실 `concept_content.k12`)이 로드되고 `review_status` 축이 전 행에 있다.

    ⚠️ 이 `review_status`는 **개념 콘텐츠 코퍼스**의 축(값: `ai_estimated`)이며, CONT-01이 건
    검수 게이트가 보는 **문항 코퍼스**의 `review_status`(값: pending/approved/rejected,
    `ReviewStatus` enum)와 *다른 축·다른 값집합*이다. 이름이 같아 혼동하기 쉬워 여기 명시한다.
    """
    rows = load_concepts(cai.DEFAULT_CONCEPT_PATH)
    assert len(rows) == _FACTS["concept_content.k12"]
    assert all(row.review_status for row in rows)


def test_shipped_index_entries_all_come_from_review_cleared_problems() -> None:
    """**커밋된 산출물**의 모든 entry가 검수 통과 문항에서 왔다 — CONT-01 게이트의 결과 동결.

    빌더에 게이트를 걸어놓고 산출물을 재생성하지 않으면 학생이 보는 것은 여전히 옛 산출물이다
    ("정본화≠집행"). 그래서 코드가 아니라 **커밋된 index.json**을 문항 코퍼스와 대조한다.

    적용 전 실측(2026-08-11): 61 entry 중 5건이 `problem_bank_v1`(review_status=pending 4/4)
    유래였다 — HK06·HK07·HK09·HK10·HK11. 적용 후 그 5건은 빠지거나 검수 통과 문항으로 대체된다.
    """
    index = json.loads((cai.DEFAULT_INDEX_DIR / "index.json").read_text(encoding="utf-8"))
    # 문항 slug → review_status (전 뱅크 전수).
    status_by_slug: dict[str, object] = {}
    for path in cai.discover_problem_files(cai.DEFAULT_CORPUS_ROOT):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            slug = record.get("slug") or record.get("problem_id")
            if slug:
                status_by_slug[str(slug)] = record.get("review_status")

    assert index[
        "entries"
    ], "산출물이 비어 있으면 이 대조는 무의미하다(측정 실패를 통과로 위장 금지)"
    offenders = [
        (entry["concept_code"], entry["problem_slug"], status_by_slug.get(entry["problem_slug"]))
        for entry in index["entries"]
        if not is_review_status_cleared(status_by_slug.get(entry["problem_slug"]))
    ]
    assert offenders == [], f"검수 미통과 문항에서 상속한 entry가 남아 있다: {offenders}"


def test_shipped_index_records_filter_drops() -> None:
    """커밋된 산출물이 5겹 탈락 집계를 싣는다 — 게이트가 몇 건을 걸렀는지 감사 가능."""
    index = json.loads((cai.DEFAULT_INDEX_DIR / "index.json").read_text(encoding="utf-8"))
    drops = index["filter_drops"]
    assert set(drops) == {
        DROP_NOT_OWN_LICENSE,
        DROP_NOT_REVIEW_CLEARED,
        DROP_REVERIFY_NOT_PASS,
        DROP_EMPTY_ANSWER_MAP,
        DROP_TIER1_NOT_PASS,
    }
    # 검수 축이 실제로 일했다 — 0이면 게이트가 무의미하거나 코퍼스가 전량 approved라는 뜻이므로
    # 그 사실 자체가 여기서 드러나야 한다(현 코퍼스에는 pending 뱅크가 실재한다).
    assert drops[DROP_NOT_REVIEW_CLEARED] > 0
