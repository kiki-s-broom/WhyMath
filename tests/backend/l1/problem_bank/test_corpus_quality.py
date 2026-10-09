"""문제 코퍼스 *품질 게이트* — 각 시드가 S2-a 수용 게이트를 통과함을 실증(계약 봉인).

"코퍼스는 S2-a 게이트 통과분"이라는 적재 계약(`l1/problem_bank/populate` 모듈 docstring)을 이
테스트가 봉인한다. 적재 파이프라인(L1)은 계층 규칙상 게이트(L3)를 부르지 않으므로, *테스트*가
계층 밖에서 L1 로더 + L3 게이트를 동시 import해 각 시드를 게이트에 태워 `accepted`(또는 최소
`verification=="verified"`)를 확인한다. verify 메타(conditions·answer_map)는 코퍼스 authoring
필드에서 읽는다. PG·LLM 불요(게이트는 순수·결정론).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l1.problem_bank.populate import ProblemBankRecord, load_problem_bank_records
from whymath_backend.l3.equivalent.acceptance import (
    EquivalenceSpec,
    evaluate_equivalent_candidate,
)
from whymath_backend.l3.equivalent.rephrase import classify_invariance_failure, extract_equation
from whymath_backend.schema.provenance import ContentProvenance


def _corpus_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "data"
        / "corpus"
        / "problem_bank_v1"
        / "problems.jsonl"
    )


def _records() -> list[ProblemBankRecord]:
    corpus = _corpus_path()
    if not corpus.exists():
        pytest.skip("실 코퍼스 미존재(data/corpus/problem_bank_v1/problems.jsonl)")
    return load_problem_bank_records(corpus)


def _evaluate(record: ProblemBankRecord) -> object:
    """시드 레코드로 EquivalenceSpec/Provenance를 조립해 S2-a 게이트에 태운다(자기-정합 spec).

    spec는 시드 자신의 대응 필드(성취기준·오개념·난이도·답형태)로 구성하므로 동등성 성분은 모두
    만점(원본=후보). 즉 정확성(verify)·저작권(provenance)·위생(본문 슬립)만이 통과의 변수다.
    """
    problem = record.problem
    misc = frozenset(entry.misconception_id for entry in (problem.distractor_map or []))
    spec = EquivalenceSpec(
        achievement_standard_codes=frozenset(problem.achievement_standard_codes),
        target_misconception_ids=misc,
        difficulty_overall=problem.difficulty_overall or 3.0,
        answer_format=problem.answer_format,
    )
    provenance = ContentProvenance(
        generation_type=record.provenance.generation_type,
        license=record.provenance.license,
        original_source=record.provenance.original_source,
    )
    return evaluate_equivalent_candidate(
        spec,
        problem,
        provenance=provenance,
        conditions=record.verify.conditions,
        answer_map=record.verify.answer_map,
        answer_selection=record.verify.answer_selection,  # 근 선택(S2-i)
        solution_steps=record.verify.solution_steps,
    )


# S2-i: "서로 다른 실근의 개수는?" 류(근의 *개수*)는 답이 근 값이 아니라 개수라 근 대입으로 자동
# 검증할 수 없다(현 conditions/answer_map 계약 밖). 정직하게 needs_review로 남긴다 — 사람 검수·
# 후속 count 검증기 소관. 이 시드만 예외(나머지는 자동 verified/accepted).
_REVIEW_ONLY_SLUGS: frozenset[str] = frozenset({"wm-quad-eq-root-count-mc"})


def test_every_seed_passes_acceptance_gate() -> None:
    records = _records()
    assert len(records) >= 3  # 손저작 시드 3~5개
    for record in records:
        verdict = _evaluate(record)
        if record.slug in _REVIEW_ONLY_SLUGS:
            # 근의 개수 문제 — 근 대입 자동검증 밖이라 정직하게 검수필요(pass 위장 금지).
            assert verdict.verification == "unverified"  # type: ignore[attr-defined]
            continue
        # 계약: 최소 정확성 검증(verified) — 시드가 S2-a 정확성 게이트를 실증.
        assert verdict.verification == "verified", (  # type: ignore[attr-defined]
            f"{record.slug} 정확성 미검증: {verdict.reasons}"  # type: ignore[attr-defined]
        )


def test_every_seed_is_accepted() -> None:
    # 더 강한 실증 — 4종 게이트 모두 통과(accepted=True). 자기-정합 spec이라 동치후보 보장.
    # 단 근의 개수 문제(_REVIEW_ONLY)는 자동검증 밖이라 needs_review(검수필요)로 남는다.
    for record in _records():
        verdict = _evaluate(record)
        if record.slug in _REVIEW_ONLY_SLUGS:
            assert verdict.accepted is False  # type: ignore[attr-defined]
            assert verdict.equivalence == "검수필요"  # type: ignore[attr-defined]
            continue
        assert verdict.accepted is True, (  # type: ignore[attr-defined]
            f"{record.slug} 미수용: {verdict.reasons}"  # type: ignore[attr-defined]
        )


def test_seeds_have_no_metadata_only_sources() -> None:
    # 저작권 레일 — 코퍼스 전건 자체생성(평가원/EBS/교과서 본문 복제 0).
    for record in _records():
        assert record.problem.source_type == "자체생성"
        assert record.provenance.license == "WHYMATH_GENERATED"


# ──────────────────────────────────────────────────────────────────────
# 생성 코퍼스(v0·사람 검수 전) — 스켈레톤 배치 산출물도 같은 게이트로 저장소 차원 봉인.
# 게이트 통과 ≠ 학생 노출(§03 정본) — 이 테스트는 "기계 검증 전건 통과"만 동결한다.
# ──────────────────────────────────────────────────────────────────────
def _generated_corpus_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "data"
        / "corpus"
        / "problem_bank_generated_v0"
        / "problems.jsonl"
    )


def _generated_records() -> list[ProblemBankRecord]:
    corpus = _generated_corpus_path()
    if not corpus.exists():
        pytest.skip("생성 코퍼스 미존재(data/corpus/problem_bank_generated_v0/problems.jsonl)")
    return load_problem_bank_records(corpus)


def test_generated_corpus_every_record_is_accepted() -> None:
    # 배치 산출물 전건이 4종 게이트를 통과(accepted) — Phaiakes9 배치 결과의 저장소 재검증.
    records = _generated_records()
    assert len(records) >= 100  # 스켈레톤 배치 가동 후 볼륨(2026-07-06: 161건)
    for record in records:
        verdict = _evaluate(record)
        assert verdict.accepted is True, (  # type: ignore[attr-defined]
            f"{record.slug} 미수용: {verdict.reasons}"  # type: ignore[attr-defined]
        )


def test_generated_corpus_copyright_rail() -> None:
    # 저작권 레일 — 생성 코퍼스 전건 자체생성·WHYMATH_GENERATED(본문성 원본 0).
    for record in _generated_records():
        assert record.problem.source_type == "자체생성"
        assert record.provenance.license == "WHYMATH_GENERATED"
        assert record.provenance.original_source is None


def test_generated_corpus_slugs_unique() -> None:
    # 멱등 upsert 키(slug) 전건 상이 — 배치 dedup·내용 주소화가 실제 산출물에서 성립.
    slugs = [record.slug for record in _generated_records()]
    assert len(slugs) == len(set(slugs))


# ──────────────────────────────────────────────────────────────────────
# S2-p 신규 불변식 — 결정론 메타(난이도·개념·distractor·무리근·구조 서명) 봉인.
# 테스트는 계층 밖이라 L3(canonicalize)·L4(validate) 교차 import가 허용된다(코퍼스 품질 재현).
# ──────────────────────────────────────────────────────────────────────
def test_generated_corpus_difficulty_varies() -> None:
    # rule-based 난이도 — 2.5 균일(스펙 미러 v0) 회귀 차단: 분산 실재 + 전건 1~5 척도.
    records = _generated_records()
    values = {record.problem.difficulty_overall for record in records}
    assert len(values) >= 3, f"난이도 균일 회귀: {values}"
    for value in values:
        assert value is not None and 1.0 <= value <= 5.0


def test_generated_corpus_concepts_tagged() -> None:
    # 결정론 개념 태깅 — 전건 비어있지 않음 + 문제군별 PRIMARY 개념(quad=HK06·이차방정식의 근,
    # calc-extremum=H:12미적Ⅰ02-07·극대극소, calc-tangent=H:12미적Ⅰ02-01·미분계수).
    # 미지 개념 태깅은 차단(태깅 왜곡 봉인).
    # exp/log(대수·H:12대수01-08)는 지수·로그 방정식 밴드.
    # 수열·삼각(대수) 밴드: 등차=H:12대수03-02·등비=H:12대수03-03·삼각=H:12대수02-02·
    # 귀납 정의(seq-inductive·S2-06)=H:12대수03-06.
    known_primary = {
        "HK06",
        "H:12미적Ⅰ02-07",
        "H:12미적Ⅰ02-01",
        "H:12대수01-08",
        "H:12대수03-02",
        "H:12대수03-03",
        "H:12대수02-02",
        "H:12대수03-06",
    }
    for record in _generated_records():
        assert record.concept_tags, f"{record.slug} concepts 비어 있음"
        primary = [t.concept_src_id for t in record.concept_tags if t.role == "PRIMARY"]
        assert primary, f"{record.slug} PRIMARY 개념 없음"
        assert set(primary) <= known_primary, f"{record.slug} 미지 PRIMARY 개념: {primary}"


def test_generated_corpus_sequence_trig_bands() -> None:
    # 수열·삼각 밴드 봉인 — 각 문제군 존재·단답형·유일해 검증(unique)·개념 태깅.
    #   등차(ARITH-SEQ)·등비(GEO-SEQ)·삼각(TRIG-VAL) unit_code로 밴드 식별.
    records = _generated_records()
    by_unit: dict[str, list[ProblemBankRecord]] = {}
    for record in records:
        unit = record.problem.unit_codes[0] if record.problem.unit_codes else ""
        by_unit.setdefault(unit, []).append(record)

    expectations = {
        "ARITH-SEQ": ("H:12대수03-02", 30),
        "GEO-SEQ": ("H:12대수03-03", 20),
        "TRIG-VAL": ("H:12대수02-02", 10),
    }
    for unit, (concept, minimum) in expectations.items():
        band = by_unit.get(unit, [])
        assert len(band) >= minimum, f"{unit} 밴드 볼륨 부족: {len(band)}"
        for record in band:
            assert record.problem.question_format == "단답형"
            assert record.verify.answer_selection == "unique"
            primary = [t.concept_src_id for t in record.concept_tags if t.role == "PRIMARY"]
            assert primary == [concept], f"{record.slug} 개념 불일치: {primary}"


def test_generated_corpus_sum_and_trig_eq_bands() -> None:
    # 수열합·삼각방정식 밴드 봉인 — 문제군 존재·단답형·자연수 답·개념 태깅·근 선택 규약.
    #   등차합(ARITH-SUM)·등비합(GEO-SUM)은 유일해(unique)·삼각방정식(TRIG-EQ)은 근 선택
    #   (smallest/largest). 삼각방정식 답은 정수 각이라 sqrt 미포함(무리근 sqrt 필터 미혼입).
    records = _generated_records()
    by_unit: dict[str, list[ProblemBankRecord]] = {}
    for record in records:
        unit = record.problem.unit_codes[0] if record.problem.unit_codes else ""
        by_unit.setdefault(unit, []).append(record)

    expectations = {
        "ARITH-SUM": ("H:12대수03-02", 30, {"unique"}),
        "GEO-SUM": ("H:12대수03-03", 15, {"unique"}),
        "TRIG-EQ": ("H:12대수02-02", 10, {"smallest", "largest"}),
    }
    for unit, (concept, minimum, selections) in expectations.items():
        band = by_unit.get(unit, [])
        assert len(band) >= minimum, f"{unit} 밴드 볼륨 부족: {len(band)}"
        for record in band:
            assert record.problem.question_format == "단답형"
            assert record.problem.answer_format == "자연수"
            assert record.verify.answer_selection in selections
            assert "sqrt(" not in (record.problem.answer or "")  # 자연수 답(무리근 필터 미혼입)
            primary = [t.concept_src_id for t in record.concept_tags if t.role == "PRIMARY"]
            assert primary == [concept], f"{record.slug} 개념 불일치: {primary}"


def test_generated_corpus_mc_invariants() -> None:
    # 객관식 밴드 — 선지 구조 + distractor 전 선지 태깅 + L4 정본 참조 무결성(validate).
    from whymath_backend.l4.misconception.validate import validate_distractor_map

    mc_records = [r for r in _generated_records() if r.problem.question_format == "객관식"]
    assert len(mc_records) >= 30  # 객관식 밴드 볼륨(기본 45)
    for record in mc_records:
        problem = record.problem
        assert problem.choices is not None and len(problem.choices) == 4
        assert len(set(problem.choices)) == 4
        assert problem.answer in problem.choices
        assert problem.distractor_map is not None and len(problem.distractor_map) == 3
        answer_index = problem.choices.index(problem.answer)
        indexes = {entry.choice_index for entry in problem.distractor_map}
        assert indexes == set(range(4)) - {answer_index}
        violations = validate_distractor_map(problem.distractor_map)
        assert violations == [], f"{record.slug} distractor 참조 무결성 위반: {violations}"


def test_generated_corpus_sqrt_records() -> None:
    # 무리근 이차 밴드 — SymPy 정확값 answer('p ± sqrt(q)')·실수 형식·근 선택(largest/smallest).
    # 삼각 밴드도 answer에 sqrt를 갖지만 selection=unique·단원 TRIG-VAL이라 근 선택으로 분리한다
    # (무리근 이차 밴드만 겨냥·삼각 sqrt 값과 혼입 방지).
    sqrt_records = [
        r
        for r in _generated_records()
        if "sqrt(" in (r.problem.answer or "")
        and r.verify.answer_selection in {"largest", "smallest"}
    ]
    assert len(sqrt_records) >= 20  # 무리근 이차 밴드 볼륨(기본 30)
    for record in sqrt_records:
        assert record.problem.answer_format == "실수"
        assert "." not in (record.problem.answer or "")  # 반올림 소수 0
        assert (record.problem.unit_codes or [""])[0] != "TRIG-VAL"  # 삼각 미혼입 재확인


def test_generated_corpus_signatures_unique_within_family() -> None:
    # 구조 서명(canonical_signature) — *문제군(unit_codes)* 내에서 전건 상이(형식 파티션 봉인:
    # 같은 방정식·선택이 단답형·객관식으로 중복 수록되면 깨진다). **문제군을 가로지른 충돌은
    # 허용**한다 — calc 극값의 conditions는 도함수 방정식이라 quad 이차방정식과 구조 동형일 수
    # 있고(다른 문제·다른 개념), 문제군별로 dedup되므로 공존이 정상이다. 전역 유일성은 slug가
    # 보장(test_generated_corpus_slugs_unique).
    from collections import defaultdict

    from whymath_backend.l3.equivalent.canonicalize import canonical_signature

    per_family: dict[str, list[str | None]] = defaultdict(list)
    for record in _generated_records():
        family = record.problem.unit_codes[0] if record.problem.unit_codes else ""
        sig = canonical_signature(record.verify.conditions, record.verify.answer_selection)
        if sig is None:
            continue  # 비다항 문제군(지수·로그)은 signature=None이 정상 — slug 유일성에 위임
        per_family[family].append(sig)
    for family, sigs in per_family.items():
        assert len(sigs) == len(set(sigs)), f"{family} 문제군 내 서명 중복"


# ──────────────────────────────────────────────────────────────────────
# rephrase 코퍼스(v0·라이브 산출) — 발문만 LLM 다양화한 산출물의 저장소 봉인.
# 핵심 계약: question_text만 바뀌고 그 외 전 필드는 소스(생성 코퍼스)와 **바이트 동일**이며,
# 발문이 바뀐 레코드는 소스 방정식이 결정론 게이트로 재검증 통과한다(수치 불변·오염 0).
# 이 테스트가 "rephrase는 표현만 바꾼다"는 안전 계약을 저장소 차원에서 영구 동결한다.
# ──────────────────────────────────────────────────────────────────────
def _rephrased_corpus_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "data"
        / "corpus"
        / "problem_bank_rephrased_v0"
        / "problems.jsonl"
    )


def _raw_by_slug(path: Path) -> dict[str, dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {str(rec["slug"]): rec for rec in records}


# S2-08 재조정 후 rephrase↔생성 조인은 slug가 아니라 **수정 불변 수학키**로 한다: 발문 조사
# 수정으로 content-hash slug이 바뀐 레코드(72건)가 있어 slug 부분집합 관계가 깨졌고, rephrase는
# 발문/slug/problem_id를 LLM 원본으로 보존하기 때문이다. 이 키(단원·조건·근선택·정답)는 조사·
# 난이도·op-code 수정에 전부 불변이고 생성 코퍼스에서 유일하다
# (scripts/reconcile_rephrased_corpus_s2_08).
def _math_key(rec: dict[str, object]) -> tuple[object, ...]:
    verify = rec["verify"]
    assert isinstance(verify, dict)
    return (
        tuple(rec["unit_codes"]),  # type: ignore[arg-type]
        verify["conditions"],
        verify["answer_selection"],
        str(rec["answer"]),
    )


def _raw_by_math_key(path: Path) -> dict[tuple[object, ...], dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    index = {_math_key(rec): rec for rec in records}
    assert len(index) == len(records), "생성 코퍼스 수학키 충돌 — 조인 불가"
    return index


def _rephrased_raw() -> dict[str, dict[str, object]]:
    corpus = _rephrased_corpus_path()
    if not corpus.exists():
        pytest.skip("rephrase 코퍼스 미존재(data/corpus/problem_bank_rephrased_v0/problems.jsonl)")
    return _raw_by_slug(corpus)


def _rephrased_records() -> list[ProblemBankRecord]:
    corpus = _rephrased_corpus_path()
    if not corpus.exists():
        pytest.skip("rephrase 코퍼스 미존재(data/corpus/problem_bank_rephrased_v0/problems.jsonl)")
    return load_problem_bank_records(corpus)


def test_rephrased_corpus_joins_source_by_math_key() -> None:
    # rephrase는 후처리(생성 X)라 산출물은 전건 소스의 같은 수학 문제에 대응한다(신 문제 창작 0).
    # S2-08 재슬러그 후 slug 부분집합 관계는 깨졌으므로 **수정 불변 수학키**로 조인해 산출이
    # 소스를 벗어나지 않음을 봉인한다(수학키는 조사·난이도·op-code 수정에 불변).
    source_keys = set(_raw_by_math_key(_generated_corpus_path()))
    rephrased = _rephrased_raw()
    assert len(rephrased) >= 1
    for slug, rec in rephrased.items():
        assert _math_key(rec) in source_keys, f"{slug} 산출이 소스 밖 수학 문제(창작 금지)"


def test_rephrased_corpus_preserves_all_fields_but_question_text() -> None:
    # 핵심 안전 봉인 — question_text 외 전 필드(answer·verify·choices·conditions·distractor·
    # 난이도·개념·서명 등)가 소스(수학키 조인)와 동일(수치·정답·검증 메타 불변·오염 0). slug·
    # problem_id는 rephrase가 LLM 원본을 보존하므로 재슬러그된 레코드에서 소스와 다를 수 있어
    # 비교에서 제외한다(S2-08·발문 조사 수정으로 소스 slug만 바뀐 경우).
    #
    # S3-27(2026-07-30) 편집자 참고 → PB-07(2026-08-11) 갱신: `problem_type_codes`는 한때
    # 소스(generated_v0)에만 있는 *의도된* 비대칭 필드였다 — `S4-14`(변형 계보 영속) 미착지로
    # 원 생성기를 추적할 수 없어 rephrased_v0는 유형 백필에서 명시 제외됐었다. 그 사유가
    # 소멸해(S4-14/S4-18 done·계보 421/421 실측) `PB-07`이 제외를 해제하고 계보(relations
    # "변형" parent_slug → 부모 유형 승계)로 rephrased에도 백필했다
    # (`problem_bank_gap_review_r3.md` §3 G2·`harness/problem_type_backfill.py`). 이제 키 집합은
    # 완전 대칭이고 값도 소스와 동일해야 한다 — 수학키 조인 소스와 unit_codes가 같고(아래 값
    # 비교가 봉인) generated_v0 분류는 unit_codes의 순수 함수이므로, 계보 승계 값과 소스 저장
    # 값이 필연 일치한다. 비대칭 제외를 걷어 값 일치까지 봉인한다.
    #
    # 병합 경위(2026-08-04, S4-18 병합): 이 병합 시점의 `rephrased_v0`는 병합 대상 브랜치와
    # 별개로 main에서 rotation-2 이후 재생성돼(S3-15 재설계) problem_id 429건 중 37건만 원
    # 코퍼스와 일치했다 — `scripts/backfill_rephrase_lineage_s4_18.py --check`로 재생성된
    # 코퍼스 위에서 드라이런 후(전량 미처리 429건 확인) 실행해 identity_id·relations를
    # 재생성 코퍼스 기준으로 다시 채웠다(멱등 스크립트 — 재실행 안전). 아래 두 어서션은 그
    # 재실행 결과가 원 브랜치의 계약(양쪽 identity_id 대칭)과 여전히 일치함을 실측 확인한
    # 뒤 살렸다.
    #
    # relations는 S4-14(스켈레톤 "유사" 형제) 병합 이후 *양쪽* 코퍼스에 키 자체는 대칭으로
    # 존재하되(키 집합 비교는 별도 제외 불요), *값*은 의도적으로 비대칭이다 — 소스는 자신의
    # "유사" 형제 태깅, rephrase 성공 레코드는 parent_slug를 향한 "변형" 태깅(S4-18)으로
    # 서로 다른 관계를 가리킨다(계보가 곧 이 차이의 요점) — 값 비교에서만 제외한다.
    #
    # PB-17(2026-10) 저작 서명 `authored_by`: 소스(generated_v0)는 결정론 생성기가 만들어 서명이
    # 백필됐지만, rephrased_v0는 **LLM이 발문을 다시 쓴** 코퍼스라 결정론 서명을 승계하면 안 된다
    # (승계하면 LLM 저작분이 `deterministic:`으로 위장돼 생성자≠검증자 가드가 면제된다). 저작 모델
    # id 는 기록돼 있지 않으므로 `llm:` 서명도 지어내지 않고 '기록 없음'으로 둔다 → 이 키만
    # 의도적 비대칭이라 키 집합·값 비교에서 제외한다(비어 있음 자체는 아래 별도 테스트가 봉인).
    source = _raw_by_math_key(_generated_corpus_path())
    rephrased = _rephrased_raw()
    exclude = {"question_text", "slug", "problem_id", "relations", "authored_by"}
    for slug, rec in rephrased.items():
        src = source[_math_key(rec)]
        assert set(rec) - {"authored_by"} == set(src) - {"authored_by"}, f"{slug} 키 집합 변화"
        for key in src:
            if key in exclude:
                continue
            assert rec[key] == src[key], f"{slug} 필드 변조: {key}"


def test_rephrased_corpus_never_inherits_a_deterministic_author() -> None:
    # PB-17 — LLM 재작성 코퍼스가 결정론 서명을 갖는 순간 가드가 거짓 면제된다. 0건을 봉인한다.
    rephrased = _rephrased_raw()
    assert rephrased, "스캔 0건"
    inherited = [slug for slug, rec in rephrased.items() if "authored_by" in rec]
    assert inherited == [], f"결정론 서명 승계 {len(inherited)}건: {inherited[:3]}"


def test_rephrased_corpus_changed_questions_preserve_equation() -> None:
    # 발문이 바뀐 레코드는 소스 방정식 문자열이 산출 발문에 보존(결정론 게이트 재검증 통과) —
    # LLM 다양화가 수식을 훼손하지 않았음을 저장소 차원에서 재확인(수학키 조인·라이브 게이트 미러).
    source = _raw_by_math_key(_generated_corpus_path())
    rephrased = _rephrased_raw()
    changed = 0
    for slug, rec in rephrased.items():
        src_q = str(source[_math_key(rec)]["question_text"])
        out_q = str(rec["question_text"])
        if out_q == src_q:
            continue
        changed += 1
        equation = extract_equation(src_q)
        assert equation is not None, f"{slug} 소스 방정식 추출 불가인데 발문 변경됨"
        failure = classify_invariance_failure(out_q, equation=equation)
        assert failure is None, f"{slug} 산출 발문이 수치 불변 게이트 위반: {failure}"
    # S3-12 rotation-1 위생 게이트 확장(443→429, 14건 추가 탈락)으로 161→147 정직 축소 —
    # 탈락 레코드는 전부 발문이 변경된(=changed) 결함 항목이라 하한도 같이 내려간다.
    assert changed >= 147, f"다양화 반영이 비정상적으로 적음: {changed}건"


def test_rephrased_corpus_every_record_is_accepted() -> None:
    # 다양화 후에도 전건이 S2-a 4종 게이트 통과(accepted) — 수치·정답·검증 메타가 불변이라
    # 정확성 게이트는 무료 재통과하고, 위생 게이트가 새 발문의 본문성 슬립까지 봉인한다.
    for record in _rephrased_records():
        verdict = _evaluate(record)
        assert verdict.accepted is True, (  # type: ignore[attr-defined]
            f"{record.slug} 미수용: {verdict.reasons}"  # type: ignore[attr-defined]
        )


def test_rephrased_corpus_copyright_rail() -> None:
    # 저작권 레일 — rephrase는 표현만 바꾸므로 자체생성·WHYMATH_GENERATED가 그대로 유지된다.
    for record in _rephrased_records():
        assert record.problem.source_type == "자체생성"
        assert record.provenance.license == "WHYMATH_GENERATED"
        assert record.provenance.original_source is None


# ──────────────────────────────────────────────────────────────────────
# 계보(identity_id·problem_relation) 거버넌스 — S4-18 소급 백필 결과 봉인.
# ──────────────────────────────────────────────────────────────────────
def test_rephrased_corpus_all_records_have_identity_id() -> None:
    records = _rephrased_records()
    assert len(records) >= 400  # 429건 실측 하한(여유 마진)
    missing = [r.slug for r in records if r.problem.identity_id is None]
    assert not missing, f"identity_id 미부여 {len(missing)}건: {missing[:5]}"


def test_rephrased_corpus_all_records_have_exactly_one_variant_relation() -> None:
    for record in _rephrased_records():
        assert len(record.relations) == 1, f"{record.slug} relations 개수 이상: {record.relations}"
        rel = record.relations[0]
        assert rel.relation_type == "변형"
        assert rel.similarity_score == 1.0  # rephrase는 conditions·answer 그대로 복사(실측 사실)


def test_rephrased_corpus_relation_parent_exists_in_generated() -> None:
    # 참조 무결성 — 계보가 가리키는 parent_slug가 실제로 생성 코퍼스에 존재한다(orphan 0건).
    generated_slugs = {rec["slug"] for rec in _raw_by_slug(_generated_corpus_path()).values()}
    for record in _rephrased_records():
        parent_slug = record.relations[0].parent_slug
        assert parent_slug in generated_slugs, f"{record.slug}의 parent_slug 미존재: {parent_slug}"


def test_rephrased_corpus_identity_id_matches_parent() -> None:
    # rephrase 변형과 그 parent(생성 코퍼스)가 같은 identity_id를 공유한다(계열 대칭성).
    generated_by_slug = _raw_by_slug(_generated_corpus_path())
    for record in _rephrased_records():
        parent_slug = record.relations[0].parent_slug
        parent_identity = generated_by_slug[parent_slug].get("identity_id")
        assert parent_identity is not None, f"parent {parent_slug}에 identity_id 미부여"
        assert (
            str(record.problem.identity_id) == parent_identity
        ), f"{record.slug}·parent {parent_slug} identity_id 불일치"


def test_no_slug_collisions_between_generated_and_rephrased() -> None:
    # S4-18 핵심 수정 — 이전엔 429건 중 392건이 원본과 slug가 같아 DB에서 한 행으로 병합됐다.
    # 백필 후에는 전량 유일해야 한다(populate.py upsert가 서로 다른 행으로 저장).
    generated_slugs = [rec["slug"] for rec in _raw_by_slug(_generated_corpus_path()).values()]
    rephrased_slugs = [r.slug for r in _rephrased_records()]
    all_slugs = generated_slugs + rephrased_slugs
    assert len(all_slugs) == len(set(all_slugs)), "생성·rephrase 코퍼스 간 slug 충돌 잔존"
