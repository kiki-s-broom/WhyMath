"""중복의 **출처** 구분 — `rejected_duplicate` 한 이름에 섞여 있던 두 사건을 가른다(EOS-121 B).

왜 이 파일이 있는가
------------------
종전에는 회차 내 중복(이번 배치가 방금 만든 것과 겹침 = *생성 다양성 문제*)과 코퍼스 중복
(기존 자산과 겹침 = *dedup 정상 동작*)이 같은 `status`·같은 reason 문자열로 찍혀 구분이
불가능했다. 원인도 처방도 다른 두 사건이라, 섞인 숫자로는 아무 판정도 못 낸다.

이 파일이 못 박는 것은 **네 가지 분기 전부**다 — 한쪽만 보면 "전부 corpus로 계상"하는 과잉
구현이 통과한다(CLAUDE.md 2026-09-08 "성공 방향 대조군"):

    구조 signature × 회차내 / 구조 signature × 코퍼스
    임베딩 과유사   × 회차내 / 임베딩 과유사   × 코퍼스 / 임베딩 과유사 × 혼재
    + 좌석 미주입 → **미판정**(None) — `corpus`로 접지 않는다
    + 중복이 아닌 outcome → 두 축 전부 None(대조군 — "항상 태그를 단다"를 배제)

경계(이 파일이 동결하는 계약): 출처 판정의 기준은 **회차가 시작된 뒤 orchestrator 자신이
추가한 것**이다. `signature_index`는 호출자 소유 가변 집합이고 호출자가 회차 전에 무엇을
넣었는지 orchestrator는 알 수 없다 — 그래서 `signature_index` 소속 여부로 판정하면 안 된다.
`test_pre_seeded_signature_is_corpus_not_round`가 정확히 그 뮤테이션을 잡는다.

저작권: 후보는 전부 자작(자체생성·WHYMATH_GENERATED)이다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from whymath_backend.l1.problem_bank.embedding import ProblemEmbeddingIndex
from whymath_backend.l1.problem_bank.populate import (
    ProblemBankPopulateReport,
    ProblemBankRecord,
)
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import CandidateProblem, ScriptedGenerator
from whymath_backend.l3.equivalent.orchestrator import (
    GenerationOutcome,
    RoundDedupScope,
    run_batch,
    run_equivalent_generation,
)
from whymath_backend.l4.misconception.semantic.provider import FakeEmbeddingProvider
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import DistractorEntry, Problem
from whymath_backend.schema.provenance import ContentProvenance

_STANDARD = "[12미적01-01]"
_MISCONCEPTION = "distribution-over-power"
_CONDITIONS = "x**2 - 5*x + 6 = 0"


def _problem(**overrides: object) -> Problem:
    kwargs: dict[str, object] = {
        "slug": "wm-dup-src-a",
        "source_type": SourceType.자체생성,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.미적분,
        "unit_codes": ["CAL-INT-DEF"],
        "difficulty_overall": 3.0,
        "answer_format": AnswerFormat.자연수,
        "achievement_standard_codes": [_STANDARD],
        "distractor_map": [DistractorEntry(choice_index=1, misconception_id=_MISCONCEPTION)],
        "question_text": "주어진 이차식의 자연수 근을 구하시오.",
        "answer": "3",
        "answer_explanation": "주어진 조건을 풀면 정답은 자연수 세 입니다.",
    }
    kwargs.update(overrides)
    return Problem(**kwargs)  # type: ignore[arg-type]


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({_STANDARD}),
        target_misconception_ids=frozenset({_MISCONCEPTION}),
        difficulty_overall=3.0,
        answer_format=AnswerFormat.자연수,
    )


def _candidate(
    *,
    slug: str = "wm-dup-src-a",
    conditions: str = _CONDITIONS,
    answer: str = "3",
    answer_selection: str | None = "largest",
) -> CandidateProblem:
    return CandidateProblem(
        problem=_problem(slug=slug, answer=answer),
        provenance=ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
        ),
        conditions=conditions,
        answer_map={"x": answer},
        answer_selection=answer_selection,
        solution_steps=None,
        concept_tags=[],
    )


def _signature_of(candidate: CandidateProblem) -> str:
    """후보의 구조 signature — 오케스트레이터가 쓰는 것과 같은 계산(픽스처가 값을 지어내지 않는다)."""
    signature = canonical_signature(candidate.conditions, candidate.answer_selection)
    assert signature is not None, "픽스처 후보는 정규화 가능해야 한다(아니면 구조 dedup을 안 탄다)"
    return signature


class _FakeStore:
    """`ProblemBankSink` 구조 호환 fake — 저장 호출만 관찰(실 DB 0)."""

    def __init__(self) -> None:
        self.calls: list[list[ProblemBankRecord]] = []

    def populate(self, records: list[ProblemBankRecord]) -> ProblemBankPopulateReport:
        self.calls.append(list(records))
        return ProblemBankPopulateReport(
            problems_loaded=len(records),
            problem_concepts_loaded=0,
            concepts_skipped=0,
            skipped_messages=[],
        )


class _FakeIndex(ProblemEmbeddingIndex):
    """결정론 임베딩 인덱스 — `hits`를 그대로 돌려주고 upsert를 캡처(엔진 미접속)."""

    def __init__(self, *, hits: Sequence[tuple[uuid.UUID, float]] = ()) -> None:
        super().__init__(provider_name="fake", model_name="fake-hash")
        self.hits: list[tuple[uuid.UUID, float]] = list(hits)
        self.upserts: list[uuid.UUID] = []

    def search(  # type: ignore[override]
        self, vector: Sequence[float], *, top_k: int
    ) -> list[tuple[uuid.UUID, float]]:
        return self.hits[:top_k]

    def upsert(  # type: ignore[override]
        self, problem_id: uuid.UUID, vector: Sequence[float], *, source_text: str
    ) -> None:
        self.upserts.append(problem_id)


def _run(
    candidate: CandidateProblem | None, **kwargs: object
) -> GenerationOutcome:  # pragma: no cover - 얇은 헬퍼
    return run_equivalent_generation(
        _spec(),
        ScriptedGenerator([candidate]),
        **kwargs,  # type: ignore[arg-type]
    )


# ──────────────────────────────────────────────────────────────────────
# 구조 signature 축 — 회차내 vs 코퍼스 vs 미판정
# ──────────────────────────────────────────────────────────────────────
class TestStructuralDuplicateOrigin:
    def test_second_candidate_in_same_round_is_round_origin(self) -> None:
        """이번 회차가 방금 만든 것과 겹침 → `round`(생성 다양성 문제).

        **이 절의 반례**: 출처를 무조건 `corpus`로 적는 구현은 여기서만 잡힌다 —
        아래 코퍼스 테스트는 그 구현에서도 초록이다.
        """
        index: set[str] = set()  # 코퍼스 비어 있음 — 겹칠 수 있는 것은 회차분뿐이다
        scope = RoundDedupScope()
        first = _run(_candidate(), signature_index=index, round_scope=scope)
        second = _run(
            _candidate(slug="wm-dup-src-b", conditions="(x-2)*(x-3) = 0"),
            signature_index=index,
            round_scope=scope,
        )
        assert first.status == "accepted"
        assert first.duplicate_detector is None and first.duplicate_origin is None
        assert second.status == "rejected_duplicate"
        assert second.duplicate_detector == "structural_signature"
        assert second.duplicate_origin == "round"
        assert any("회차내" in reason for reason in second.reasons)

    def test_pre_seeded_signature_is_corpus_not_round(self) -> None:
        """회차 **시작 전** 호출자가 채운 signature와 겹침 → `corpus`(dedup 정상 동작).

        **이 절의 반례**: 판정을 `signature_index` 소속으로 하는 구현(= 회차 장부를 안 보는
        구현)은 여기서 `round`를 내며 실패한다 — 그 signature도 인덱스에는 있기 때문이다.
        경계 계약("회차 시작 뒤 orchestrator 자신이 추가한 것")을 동결하는 자리다.
        """
        candidate = _candidate()
        index: set[str] = {_signature_of(candidate)}  # 호출자가 기존 코퍼스로 미리 채움
        scope = RoundDedupScope()  # 회차는 아직 아무것도 추가하지 않았다
        outcome = _run(candidate, signature_index=index, round_scope=scope)
        assert outcome.status == "rejected_duplicate"
        assert outcome.duplicate_detector == "structural_signature"
        assert outcome.duplicate_origin == "corpus"
        assert any("코퍼스" in reason for reason in outcome.reasons)

    def test_without_scope_origin_is_unresolved_not_corpus(self) -> None:
        """출처 좌석 미주입 → 출처 `None`=**미판정**(검출기는 그대로 있다).

        **이 절의 반례**: 미판정을 `corpus`로 접는 구현은 여기서 잡힌다. 모르는 것을 확정으로
        적으면 생성 다양성 문제가 영영 0으로 보인다(「모른다 ≠ 아니다」).
        """
        candidate = _candidate()
        index: set[str] = {_signature_of(candidate)}
        outcome = _run(candidate, signature_index=index)  # round_scope 미주입
        assert outcome.status == "rejected_duplicate"
        assert outcome.duplicate_detector == "structural_signature"
        assert outcome.duplicate_origin is None
        assert any("미판정" in reason for reason in outcome.reasons)

    def test_accepted_candidate_registers_signature_in_scope_even_in_dry_run(self) -> None:
        """저장 좌석이 없어도 회차 장부에 실린다 — dry-run에서도 배치 내 판박이를 잡아야 하므로.

        장부와 인덱스가 **같은 자리에서** 갱신된다는 계약(둘이 갈리면 출처 판정이 거짓이 된다).
        """
        index: set[str] = set()
        scope = RoundDedupScope()
        candidate = _candidate()
        outcome = _run(candidate, signature_index=index, round_scope=scope)
        assert outcome.status == "accepted"
        assert _signature_of(candidate) in index
        assert scope.signatures == index

    def test_non_duplicate_outcomes_carry_no_duplicate_axes(self) -> None:
        """**성공 방향 대조군** — 중복이 아니면 두 축 다 None.

        이것이 없으면 "무조건 structural_signature를 단다"는 과잉 구현이 통과하고, 그러면
        교차표의 분모가 통째로 거짓이 된다.
        """
        scope = RoundDedupScope()
        accepted = _run(_candidate(), signature_index=set(), round_scope=scope)
        failed = _run(None, signature_index=set(), round_scope=scope)
        assert accepted.status == "accepted"
        assert failed.status == "generation_failed"
        for outcome in (accepted, failed):
            assert outcome.duplicate_detector is None
            assert outcome.duplicate_origin is None

    def test_run_batch_classifies_round_duplicates_by_default(self) -> None:
        """`run_batch`는 좌석을 안 줘도 장부를 **스스로** 만든다(signature_index와 같은 규약).

        배치가 기본으로 분류하지 않으면 기존 배치 호출부 전체의 중복 통계가 미판정이 된다.
        """
        outcomes = run_batch(
            _spec(),
            ScriptedGenerator(
                [_candidate(), _candidate(slug="wm-dup-src-b", conditions="(x-2)*(x-3) == 0")]
            ),
            2,
        )
        assert [o.status for o in outcomes] == ["accepted", "rejected_duplicate"]
        assert outcomes[1].duplicate_origin == "round"

    def test_run_batch_honours_caller_scope(self) -> None:
        """호출자가 장부를 주면 그것을 쓴다 — 회차 경계를 호출자가 소유하는 경우(CLI가 그렇다)."""
        scope = RoundDedupScope()
        run_batch(_spec(), ScriptedGenerator([_candidate()]), 1, round_scope=scope)
        assert len(scope.signatures) == 1


# ──────────────────────────────────────────────────────────────────────
# 임베딩 과유사 축 — 검출기가 갈리고, 출처는 upsert 이력으로 갈린다
# ──────────────────────────────────────────────────────────────────────
class TestEmbeddingDuplicateOrigin:
    def test_embedding_hit_is_tagged_embedding_near_not_structural(self) -> None:
        """임베딩 경로의 중복은 **검출기가 다르다** — 구조 signature와 한 칸에 섞이면 안 된다.

        두 경로가 같은 `status`를 공유하므로, 검출기 축이 없으면 "구조가 겹쳤나 의미가
        겹쳤나"가 사라진다(처방이 다르다: 전자는 계수 선택 폭, 후자는 서사 다양성).
        """
        existing = uuid.uuid4()  # 회차가 upsert한 적 없는 id = 기존 코퍼스
        index = _FakeIndex(hits=[(existing, 0.99)])
        scope = RoundDedupScope()
        outcome = _run(
            _candidate(),
            signature_index=set(),
            round_scope=scope,
            dedup_index=index,
            embed_provider=FakeEmbeddingProvider(dim=8),
        )
        assert outcome.status == "rejected_duplicate"
        assert outcome.duplicate_detector == "embedding_near"
        assert outcome.duplicate_origin == "corpus"

    def test_embedding_hit_on_this_round_upsert_is_round_origin(self) -> None:
        """이번 회차가 저장하며 upsert한 문제와 과유사 → `round`.

        **이 절의 반례**: 임베딩 출처를 항상 `corpus`로 적는 구현은 여기서만 잡힌다.
        """
        index = _FakeIndex()
        scope = RoundDedupScope()
        store = _FakeStore()
        provider = FakeEmbeddingProvider(dim=8)
        first = _run(
            _candidate(),
            signature_index=set(),
            round_scope=scope,
            dedup_index=index,
            embed_provider=provider,
            store=store,
        )
        assert first.status == "accepted_stored"
        assert first.stored_problem_id is not None
        assert scope.problem_ids == {first.stored_problem_id}

        # 방금 저장한 그 문제가 과유사 상대로 잡히는 상황(실경로와 동형 — upsert된 벡터가 걸린다).
        index.hits = [(first.stored_problem_id, 0.99)]
        second = _run(
            _candidate(slug="wm-dup-src-b", conditions="x**2 - 7*x + 12 = 0", answer="4"),
            signature_index=set(),
            round_scope=scope,
            dedup_index=index,
            embed_provider=provider,
            store=store,
        )
        assert second.status == "rejected_duplicate"
        assert second.duplicate_detector == "embedding_near"
        assert second.duplicate_origin == "round"

    def test_embedding_hit_on_both_is_mixed(self) -> None:
        """회차분과 기존분에 **동시에** 걸리면 `mixed`.

        과유사는 여러 건과 한 번에 걸리므로 이진 판정이 성립하지 않는다. 한 건이라도 기존
        코퍼스가 섞였으면 "회차가 만든 것 때문에 막혔다"고 말할 수 없고, 반대로 전부 회차분이면
        코퍼스 dedup은 아무 일도 하지 않은 것이다 — 두 처방이 다르다.
        """
        index = _FakeIndex()
        scope = RoundDedupScope()
        store = _FakeStore()
        provider = FakeEmbeddingProvider(dim=8)
        first = _run(
            _candidate(),
            signature_index=set(),
            round_scope=scope,
            dedup_index=index,
            embed_provider=provider,
            store=store,
        )
        assert first.stored_problem_id is not None
        index.hits = [(first.stored_problem_id, 0.99), (uuid.uuid4(), 0.98)]
        second = _run(
            _candidate(slug="wm-dup-src-b", conditions="x**2 - 7*x + 12 = 0", answer="4"),
            signature_index=set(),
            round_scope=scope,
            dedup_index=index,
            embed_provider=provider,
            store=store,
        )
        assert second.duplicate_origin == "mixed"

    def test_embedding_origin_unresolved_without_scope(self) -> None:
        """좌석 미주입이면 임베딩 경로도 **미판정**이다(구조 경로와 같은 규약)."""
        index = _FakeIndex(hits=[(uuid.uuid4(), 0.99)])
        outcome = _run(
            _candidate(),
            signature_index=set(),
            dedup_index=index,
            embed_provider=FakeEmbeddingProvider(dim=8),
        )
        assert outcome.duplicate_detector == "embedding_near"
        assert outcome.duplicate_origin is None

    def test_dry_run_does_not_register_problem_id_in_scope(self) -> None:
        """저장하지 않으면 `problem_ids`에 실리지 않는다 — upsert가 없었으므로 회차분이 아니다.

        **이 절의 반례**: 수용만 하면 무조건 장부에 넣는 구현은 여기서 잡힌다. 그런 구현은
        dedup_index에 없는 id를 '회차분'이라 주장하게 되어 `mixed` 판정을 오염시킨다.
        """
        scope = RoundDedupScope()
        outcome = _run(_candidate(), signature_index=set(), round_scope=scope)  # store 미주입
        assert outcome.status == "accepted"
        assert scope.problem_ids == set()
        assert scope.signatures  # 구조 축은 dry-run에서도 쌓인다(두 축의 조건이 다르다)
