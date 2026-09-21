"""자체생성 동등문제 *생성 오케스트레이터* — S2 파이프라인 end-to-end 결선(S2-d).

S2 부품을 하나로 잇는 마지막 조각이다. 학생 노출 코퍼스에 자체생성 동등문제 1건이 들어가려면
다음 4단계를 *순서대로* 통과해야 하며, 이 모듈이 그 순수 조합을 소유한다(각 단계의 *구현*은 이미
있는 부품이 소유 — 재구현 0):

    생성(S2-d generator) → 수용 게이트(S2-a acceptance) → 과유사 dedup(S2-c embedding)
        → 코퍼스 저장(S2-b problem_bank)

**순수 조합 + 주입 효과**: 이 함수는 결정론 조합 로직만 담고, DB·임베딩 같은 *효과*는 전부 주입된
좌석(`store`·`dedup_index`·`embed_provider`)으로만 일으킨다. 좌석을 주입하지 않으면 그 단계를
건너뛴다 — dedup_index/embed_provider 없으면 dedup 스킵(순수 결정 모드), store 없으면 dry-run
(저장 안 함). 덕분에 전 분기를 실 DB 없이 hermetic하게 못 박을 수 있다(WH-S `run_solver`가 저장소를
주입받아 결정론으로 도는 것과 동형).

**정직성(CLAUDE.md "조용한 실패 금지")**: 모든 거부/검수/중복 사유는 `GenerationOutcome.reasons`에
쌓인다(게이트 사유는 게이트가 이미 채운 것을 이어붙임). 저장 성공만이 `accepted_stored`이며, 저장
좌석을 안 주면 `accepted`(검증은 통과했으나 저장 안 함)로 정직히 구분한다.

7계층: 생성(=LLM 라우터 도메인)은 **L3**다. 오케스트레이터는 L3 게이트(acceptance)·L1 저장
(problem_bank populate)·L1 dedup(problem_bank embedding)·L1 임베딩 provider(embedding_primitives)를
*하향/동계층*으로만 import한다(import-linter L3→L1 허용·L1→L3 역참조는 계약이 차단). L1 부품이
"언제 dedup을 걸지"를 모른 채 순수 질의만 소유하도록 둔 설계(embedding.py docstring)를 여기서
결선한다 — dedup 게이트를 *부르는* 책임이 바로 이 생성 파이프라인이다.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableSet
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l1.embedding_primitives import EmbeddingProvider
from whymath_backend.l1.problem_bank.embedding import (
    ProblemEmbeddingIndex,
    find_near_duplicates,
    problem_embedding_text,
)
from whymath_backend.l1.problem_bank.populate import (
    ProblemBankPopulateReport,
    ProblemBankRecord,
    ProblemProvenanceMeta,
    ProblemVerifyMeta,
)
from whymath_backend.l3.equivalent.acceptance import (
    AcceptanceVerdict,
    EquivalenceSpec,
    evaluate_equivalent_candidate,
)
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.generator import (
    CandidateProblem,
    EquivalentProblemGenerator,
)
from whymath_backend.schema.enums import GenerationType, LicenseType, SourceType

__all__ = [
    "DuplicateDetector",
    "DuplicateOrigin",
    "GenerationOutcome",
    "ProblemBankSink",
    "RoundDedupScope",
    "run_batch",
    "run_equivalent_generation",
]

# 과유사 dedup 기본 임계값 — S2-c 좌석 상수(코사인 0.97·"거의 동일" 밴드)를 그대로 물려받는다.
# (`l1/problem_bank/embedding._NEAR_DUPLICATE_THRESHOLD`와 같은 값·같은 근거 — 판박이만 거른다.)
_DEFAULT_DEDUP_THRESHOLD = 0.97


# ──────────────────────────────────────────────────────────────────────────────
# 중복의 *출처* 구분(EOS-121 선결조건 B)
#
# 종전에는 `rejected_duplicate` 1종이 서로 **원인도 처방도 다른 두 사건**을 같은 글자로 찍었다:
#   ⓐ **회차 내 중복** — 이번 배치가 방금 만든 것과 겹쳤다 = *생성 다양성*이 낮다(모델·프롬프트
#      쪽 문제. 처방은 spec을 가르거나 샘플링을 바꾸는 것).
#   ⓑ **코퍼스 중복** — 기존 자산과 겹쳤다 = dedup이 *정상 동작*한 것(처방 없음. 오히려 이 값이
#      0이면 회차 간 dedup이 안 걸린다는 신호다).
# 둘이 한 칸에 섞이면 "중복 4/5"라는 숫자로부터 아무 판정도 못 낸다. 그래서 상태 이름(`status`)은
# 그대로 두고(**기존 소비자 호환** — 리포트·카나리 `evaluate_canary`·검수 큐·테스트가 이 Literal을
# 읽는다) *출처 필드 2축*을 결과 객체에 **추가**한다.
#
# 축이 둘인 이유: "무엇이 잡았나"(검출기)와 "무엇과 겹쳤나"(출처)는 독립이다. 구조 signature와
# 임베딩 과유사는 각각 회차 내·코퍼스 양쪽에서 날 수 있으므로, 한 축으로 접으면 다시 섞인다.
DuplicateDetector = Literal["structural_signature", "embedding_near"]
"""중복을 잡은 **검출기** — 구조 signature(S2-l·SymPy 정규형) vs 임베딩 과유사(S2-c·코사인)."""

DuplicateOrigin = Literal["round", "corpus", "mixed"]
"""중복 상대의 **출처** — 이번 회차가 추가한 것/그 전부터 있던 것/둘이 섞임(임베딩 다건 판정).

`mixed`는 임베딩 경로에서만 날 수 있다(과유사는 여러 건과 동시에 걸린다). 구조 signature는
단일 값 대조라 `round`·`corpus` 둘 중 하나다.
"""


@dataclass(slots=True)
class RoundDedupScope:
    """**이 회차가 시작된 뒤 오케스트레이터 자신이 인덱스에 추가한 것**의 장부(출처 판정 기준).

    이 경계가 이 클래스의 존재 이유다. `signature_index`는 **호출자가 소유한 가변 집합**이고,
    호출자는 회차 시작 전에 기존 코퍼스 signature를 미리 채워 넣는다
    (`problem_corpus_accumulate`: `seed_signatures | out_signatures`). 오케스트레이터는 그
    집합을 넘겨받을 뿐이므로 **"이 값이 원래 있던 것인지 방금 내가 넣은 것인지"를 사후에 알
    방법이 없다** — 초기 집합을 통째로 복사해 두는 방법도 있으나 회차마다 코퍼스 전체를 한 벌
    더 들고 있게 되고, 무엇보다 *의도*가 어긋난다(우리가 알고 싶은 것은 "기존 코퍼스가 무엇인가"가
    아니라 "이번 회차가 무엇을 만들었는가"다).

    그래서 구분 기준을 **회차 시작 뒤 orchestrator 자신이 추가한 것**으로 잡고, 그 추가분만
    여기에 모은다. 판정은 대조 한 번이다:
      - 중복 상대가 이 장부에 있다 → `round`(이번 회차가 방금 만든 것과 겹침 = 생성 다양성)
      - 없다 → `corpus`(회차 시작 시점에 이미 있던 것 = dedup 정상 동작)
      - 이 좌석을 **주입하지 않으면** → 출처 `None`(**미판정** — `corpus`로 접지 않는다.
        「모른다 ≠ 아니다」. 모르는 것을 corpus로 적으면 생성 다양성 문제가 영영 0으로 보인다)

    **한계(명시)**: 호출자가 이 장부를 회차 사이에 재사용하면(새로 만들지 않으면) 이전 회차의
    추가분이 `round`로 계상된다 — 장부의 수명이 곧 "회차"의 정의다. 회차마다 새 인스턴스를
    만드는 것이 호출자 계약이며, `run_batch`는 그것을 스스로 지킨다.
    """

    signatures: set[str] = field(default_factory=set)
    """이 회차에 orchestrator가 `signature_index`에 추가한 구조 signature."""

    problem_ids: set[uuid.UUID] = field(default_factory=set)
    """이 회차에 orchestrator가 `dedup_index`에 upsert한 problem_id(임베딩 출처 판정 재료)."""


#: 출처 → 사람이 읽는 라벨(사유 문자열용). **미판정(None)도 어휘에 있다** — 라벨을 안 붙이면
#: 검수자가 "출처 표기가 없는 행"을 구판으로 읽을지 미판정으로 읽을지 알 수 없다(침묵 금지).
_ORIGIN_LABELS: dict[DuplicateOrigin | None, str] = {
    "round": "회차내(이번 배치가 방금 만든 것과 겹침 — 생성 다양성)",
    "corpus": "코퍼스(회차 시작 시점에 이미 있던 것 — dedup 정상 동작)",
    "mixed": "혼재(회차분·기존 코퍼스 양쪽과 겹침)",
    None: "미판정(출처 판정 좌석 미주입)",
}


def _classify_signature_origin(
    signature: str, round_scope: RoundDedupScope | None
) -> DuplicateOrigin | None:
    """구조 signature 중복의 출처 — 장부에 있으면 `round`, 없으면 `corpus`, 좌석 없으면 None."""
    if round_scope is None:
        return None
    return "round" if signature in round_scope.signatures else "corpus"


def _classify_embedding_origin(
    near: list[tuple[uuid.UUID, float]], round_scope: RoundDedupScope | None
) -> DuplicateOrigin | None:
    """임베딩 과유사 중복의 출처 — 전부 회차분이면 `round`, 전무면 `corpus`, 섞이면 `mixed`.

    과유사는 **여러 건과 동시에** 걸리므로 이진 판정이 성립하지 않는다. 한 건이라도 기존
    코퍼스와 겹쳤으면 "이번 회차가 만든 것 때문에 막혔다"고 말할 수 없고, 반대로 전부 회차분이면
    코퍼스 dedup은 아무 일도 하지 않은 것이다 — 그 둘을 한 값으로 접으면 처방이 갈리지 않는다.
    `near`가 비면(호출 계약상 일어나지 않는다) 판정 대상이 없으므로 None=미판정.
    """
    if round_scope is None or not near:
        return None
    hit_ids = {problem_id for problem_id, _ in near}
    from_round = hit_ids & round_scope.problem_ids
    if not from_round:
        return "corpus"
    if from_round == hit_ids:
        return "round"
    return "mixed"


@runtime_checkable
class ProblemBankSink(Protocol):
    """코퍼스 저장 좌석 — 레코드 배치를 `problem`/`problem_concept`에 멱등 upsert(적재 리포트 반환).

    S2-b `ProblemBankStore.populate`와 *구조적으로 동일*한 좌석이라 실 store가 그대로 주입된다.
    테스트는 이 좌석을 구현하는 capturing fake를 주입해 실 DB 없이 저장 호출을 관찰한다(hermetic).
    오케스트레이터는 후보 1건을 단일 레코드 배치(`[record]`)로 넘겨 S2-b의 단건 저장 seam을
    재사용한다(신규 저장 경로 0 — 배치 upsert 규약·concept 해석·orphan skip을 그대로 물려받음).
    """

    def populate(self, records: list[ProblemBankRecord]) -> ProblemBankPopulateReport:
        """레코드 배치를 멱등 적재하고 리포트를 반환."""
        ...


class GenerationOutcome(BaseModel):
    """오케스트레이터 1회 실행 결과 — 최종 상태 + 각 단계 산출물 + 사유(감사·운영·학생 비노출).

    `status` 6종:
      - `accepted_stored` — 게이트·dedup 통과 + 저장 좌석에 실제 적재 완료(`stored_problem_id`).
      - `accepted` — 게이트·dedup 통과했으나 저장 좌석 미주입(dry-run·저장 안 함).
      - `rejected_gate` — S2-a 수용 게이트에서 거부(저작권·정확성·위생·비동치·동치 아님).
      - `needs_review` — 게이트가 `검수필요`로 분류(사람 검수 큐 — 자동 저장 보류).
      - `rejected_duplicate` — S2-c 과유사 게이트에서 코퍼스 판박이로 판정(저장 차단).
      - `generation_failed` — 생성기가 후보를 내지 못함(None).

    `reasons`는 모든 거부/검수/중복 사유의 누적(조용한 실패 금지). `near_duplicates`는 과유사로
    잡힌 (problem_id, 코사인 유사도) 목록이다.

    **중복의 출처(EOS-121 선결조건 B)**: `rejected_duplicate` 한 이름 안에 원인도 처방도 다른
    사건들이 섞여 있었다. `status` 이름은 하위 호환으로 그대로 두고(소비자가 이 Literal을 읽는다)
    `duplicate_detector`·`duplicate_origin` 2축을 **추가**해 구분한다 — 모듈 상단
    `DuplicateDetector`·`DuplicateOrigin`·`RoundDedupScope` 주석이 그 경계의 정본이다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal[
        "accepted_stored",
        "accepted",
        "rejected_gate",
        "rejected_duplicate",
        "needs_review",
        "generation_failed",
    ] = Field(description="파이프라인 최종 판정(6종).")
    candidate: CandidateProblem | None = Field(
        default=None,
        description="평가 대상 후보(생성 실패 시 None).",
    )
    acceptance: AcceptanceVerdict | None = Field(
        default=None,
        description="S2-a 게이트 판정(생성 실패 시 None).",
    )
    near_duplicates: list[tuple[uuid.UUID, float]] = Field(
        default_factory=list,
        description="과유사로 잡힌 (problem_id, 유사도) 목록(rejected_duplicate 시 비지 않음).",
    )
    stored_problem_id: uuid.UUID | None = Field(
        default=None,
        description="저장된 문제 problem_id(accepted_stored 시에만).",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="거부/검수/중복 사유 누적(사람 가독·학생 비노출·조용한 실패 금지).",
    )
    duplicate_detector: DuplicateDetector | None = Field(
        default=None,
        description=(
            "중복을 잡은 검출기(EOS-121 B). `rejected_duplicate`일 때만 값이 있고 그 외 상태에선 "
            "항상 None이다 — 즉 `detector is None`은 '중복이 아니다'를 뜻한다."
        ),
    )
    duplicate_origin: DuplicateOrigin | None = Field(
        default=None,
        description=(
            "중복 상대의 출처(EOS-121 B). **`detector`가 있는데 이 값이 None이면 '미판정'이다** "
            "— 출처 판정 좌석(`round_scope`)을 주입하지 않은 회차. `corpus`로 접지 않는 이유는 "
            "모르는 것을 확정으로 적으면 생성 다양성 문제가 영영 0으로 보이기 때문이다."
        ),
    )


def _enum_value(value: object) -> str | None:
    """enum/문자열/None을 문자열 값으로 정규화(use_enum_values=True 대응·acceptance 미러)."""
    if value is None:
        return None
    if isinstance(value, (SourceType, LicenseType, GenerationType)):
        return str(value.value)
    return str(value)


def _to_record(
    candidate: CandidateProblem, *, verification_tier: str | None = None
) -> ProblemBankRecord:
    """후보 번들 → S2-b 저장 레코드(단건). slug·problem·concept_tags·verify·provenance 조립.

    저장 seam(`ProblemBankStore.populate`)이 소비하는 것은 slug·problem·concept_tags뿐이나,
    `ProblemBankRecord`는 authoring 메타(verify·provenance)도 필드로 요구하므로 후보에서 그대로
    옮겨 담는다(적재엔 미사용·계약 충족). 안정 키 `slug`는 멱등 upsert의 근간이라 후보 문제에
    반드시 있어야 한다 — 없으면 fail-loud(생성기 계약 위반·조용한 통과 금지).

    `verification_tier`(S4-13·S4-17)는 후보가 아니라 *배치 호출자*가 아는 정보(어떤 검증 방식을
    거쳤는지)라 `CandidateProblem` 필드가 아니라 이 함수의 별도 주입 인자로 받는다.
    """
    slug = candidate.problem.slug
    if not slug:
        raise ValueError(
            "저장 대상 후보의 problem.slug가 비어 있습니다 — 멱등 upsert 안정 키가 없어 저장할 수 "
            "없습니다(생성기가 slug를 채워야 합니다)."
        )
    return ProblemBankRecord(
        slug=slug,
        problem=candidate.problem,
        concept_tags=tuple(candidate.concept_tags),
        verify=ProblemVerifyMeta(
            conditions=candidate.conditions,
            answer_map=dict(candidate.answer_map),
            solution_steps=candidate.solution_steps,
            # 근 선택(S2-i)을 함께 영속 — 빠뜨리면 저장 코퍼스가 품질 게이트에서 "선택 미명시"
            # 유일성 강등을 당한다(라운드트립 실측 회귀).
            answer_selection=candidate.answer_selection,
            answer_aggregate=candidate.answer_aggregate,
            answer_kind=candidate.answer_kind,
            verification_tier=verification_tier,
        ),
        provenance=ProblemProvenanceMeta(
            generation_type=_enum_value(candidate.provenance.generation_type) or "",
            license=_enum_value(candidate.provenance.license) or "",
            original_source=_enum_value(candidate.provenance.original_source),
        ),
    )


def run_equivalent_generation(
    spec: EquivalenceSpec,
    generator: EquivalentProblemGenerator,
    *,
    dedup_index: ProblemEmbeddingIndex | None = None,
    embed_provider: EmbeddingProvider | None = None,
    signature_index: MutableSet[str] | None = None,
    round_scope: RoundDedupScope | None = None,
    store: ProblemBankSink | None = None,
    dedup_threshold: float = _DEFAULT_DEDUP_THRESHOLD,
    verification_tier: str | None = None,
) -> GenerationOutcome:
    """동등문제 후보 1건을 생성→게이트→dedup→저장으로 흘려 최종 판정을 낸다(순수 조합·주입 효과).

    파이프라인(각 단계 실패 시 조기 종료·사유는 `reasons`에 누적):
      1. **생성**(S2-d) — `generator.generate(spec)`. None이면 `generation_failed`.
      2. **수용 게이트**(S2-a) — `evaluate_equivalent_candidate`. `accepted`가 아니면 게이트가
         `검수필요`로 분류했으면 `needs_review`, 그 외(저작권/정확성/위생/비동치)는 `rejected_gate`.
      3. **과유사 dedup**(S2-c·`dedup_index`+`embed_provider` 주입 시) — 후보 발문을 임베딩해
         `find_near_duplicates`로 코퍼스와 비교, 과유사면 `rejected_duplicate`.
      4. **저장**(S2-b·`store` 주입 시) — 후보를 `problem`/`problem_concept`에 멱등 적재하고
         (임베딩 좌석까지 주면) 그 벡터를 `dedup_index`에 upsert해 *이후 후보가 이 문제를 코퍼스
         중복으로 보게* 한다(배치 누적 dedup 근간). `accepted_stored`. store 미주입이면 `accepted`.

    좌석 주입 규약:
      - `signature_index`(S2-l 구조 dedup·`MutableSet[str]`) 주면 임베딩 전에 SymPy 정규형
        signature로 판박이를 결정론 차단(임베딩 불요·비용 0). 미주입이면 이 단계 스킵.
      - `round_scope`(EOS-121 B·`RoundDedupScope`) 주면 중복의 **출처**(회차 내 vs 코퍼스)를
        판정해 `duplicate_origin`에 싣는다. 미주입이면 출처는 `None`=미판정이다(중복 판정 자체는
        그대로 난다 — 이 좌석은 *계측*이지 *차단*이 아니다). 경계 정의는 `RoundDedupScope` 참조:
        기준은 "회차가 시작된 뒤 **이 오케스트레이터가** 추가한 것"이며, 호출자가 회차 전에
        `signature_index`에 무엇을 넣었는지는 알 수 없다(그래서 그것을 기준으로 삼지 않는다).
      - `dedup_index`·`embed_provider` 둘 다 줘야 임베딩 dedup이 돈다(하나만 주면 스킵·순수 결정).
      - `store` 없으면 dry-run(검증만·저장 0). 저장 후 임베딩 영속은 `dedup_index`+`embed_provider`
        가 함께 주입됐을 때만 일어난다(임베딩 저장소 seam이 곧 dedup_index — 같은 벡터 재사용).
      - `verification_tier`(S4-17)는 저장 시에만 의미가 있다 — `_to_record`로 그대로 전달돼
        `verify.verification_tier`로 영속된다. 미주입(`None`)이면 등급 미각인(구코퍼스 호환).
    """
    reasons: list[str] = []

    # ── 1. 생성(S2-d) ──
    candidate = generator.generate(spec)
    if candidate is None:
        return GenerationOutcome(
            status="generation_failed",
            reasons=["생성기가 후보를 반환하지 못했습니다(None) — 생성 실패."],
        )

    # ── 2. 수용 게이트(S2-a) ──
    verdict = evaluate_equivalent_candidate(
        spec,
        candidate.problem,
        provenance=candidate.provenance,
        conditions=candidate.conditions,
        answer_map=candidate.answer_map,
        solution_steps=candidate.solution_steps,
        answer_selection=candidate.answer_selection,
        answer_aggregate=candidate.answer_aggregate,
        answer_kind=candidate.answer_kind,
    )
    reasons.extend(verdict.reasons)
    if not verdict.accepted:
        # 게이트가 `검수필요`로 보냈으면 needs_review(사람 큐), 그 외는 rejected_gate(거부).
        status: Literal["needs_review", "rejected_gate"] = (
            "needs_review" if verdict.equivalence == "검수필요" else "rejected_gate"
        )
        return GenerationOutcome(
            status=status,
            candidate=candidate,
            acceptance=verdict,
            reasons=reasons,
        )

    # ── 3a. 구조 dedup(S2-l·`signature_index` 주입 시) — 임베딩 전 결정론 판박이 차단 ──
    # 조건을 SymPy 정규형 signature로 접어(계수 스케일·부호·인수분해·등호표기·발문 문구 무관)
    # 이미 본 구조면 rejected_duplicate. 임베딩 없이 비용 0으로 같은 방정식의 표현 변형을 잡는다.
    # 정규화 불가(비다항 등)면 signature=None → 이 단계 스킵(임베딩 dedup에 위임).
    signature: str | None = None
    if signature_index is not None:
        # aggregate·개수형 문항은 answer_selection=None이라 같은 조건식의 변형이 충돌한다 —
        # signature payload를 집계/개수 종류로 구분(생성기 skip과 정합).
        _sig_payload = (
            candidate.answer_selection
            or (f"agg:{candidate.answer_aggregate}" if candidate.answer_aggregate else None)
            or (f"kind:{candidate.answer_kind}" if candidate.answer_kind else None)
        )
        signature = canonical_signature(candidate.conditions, _sig_payload)
        if signature is not None and signature in signature_index:
            # 출처 판정(EOS-121 B) — 사유 문자열에도 실어 검수 큐 행만 봐도 갈린다.
            # 접두 "구조 중복"은 기존 소비자·테스트가 읽으므로 보존한다(뒤에만 덧붙인다).
            origin = _classify_signature_origin(signature, round_scope)
            reasons.append(
                "구조 중복 — 정규형이 같은 방정식·근 선택이 이미 코퍼스에 있음"
                "(표현만 다른 판박이·저장 차단·S2-l)."
                f" 출처={_ORIGIN_LABELS[origin]}"
            )
            return GenerationOutcome(
                status="rejected_duplicate",
                candidate=candidate,
                acceptance=verdict,
                reasons=reasons,
                duplicate_detector="structural_signature",
                duplicate_origin=origin,
            )

    # ── 3b. 과유사 dedup(S2-c) — 좌석 둘 다 주입 시에만 ──
    candidate_vec: list[float] | None = None
    if dedup_index is not None and embed_provider is not None:
        text = problem_embedding_text(candidate.problem)
        candidate_vec = embed_provider.embed([text])[0]
        near = find_near_duplicates(dedup_index, candidate_vec, threshold=dedup_threshold)
        if near:
            origin = _classify_embedding_origin(near, round_scope)
            reasons.append(
                f"과유사 중복 — 기존 코퍼스 {len(near)}건과 코사인 ≥ {dedup_threshold}"
                "(거의 동일한 판박이·저장 차단)."
                f" 출처={_ORIGIN_LABELS[origin]}"
            )
            return GenerationOutcome(
                status="rejected_duplicate",
                candidate=candidate,
                acceptance=verdict,
                near_duplicates=near,
                reasons=reasons,
                duplicate_detector="embedding_near",
                duplicate_origin=origin,
            )

    # 두 dedup을 통과한 신규 문제 — 이후 후보가 이 구조를 중복으로 보게 signature를 등록한다
    # (배치 누적 구조 dedup·저장 여부 무관·dry-run에서도 배치 내 판박이를 잡는다).
    if signature is not None and signature_index is not None:
        signature_index.add(signature)
        # 같은 자리에서 회차 장부에도 적는다(EOS-121 B) — 따로 순회하면 두 집합이 갈려
        # "인덱스엔 있는데 장부엔 없는" signature가 생기고, 그 순간 출처 판정이 거짓이 된다.
        if round_scope is not None:
            round_scope.signatures.add(signature)

    # ── 4. 저장(S2-b) — 좌석 주입 시에만 ──
    if store is not None:
        record = _to_record(candidate, verification_tier=verification_tier)
        store.populate([record])
        # 저장한 문제의 발문 벡터를 dedup_index에 영속 — 이후 후보가 이 문제를 코퍼스 중복으로
        # 보게 한다(배치 누적 dedup). dedup 단계에서 이미 계산한 벡터를 재사용(재임베딩 0).
        if dedup_index is not None and embed_provider is not None:
            if candidate_vec is None:  # 방어(위 dedup 블록이 항상 채우나 명시) — pragma: no cover
                candidate_vec = embed_provider.embed([problem_embedding_text(candidate.problem)])[0]
            dedup_index.upsert(
                candidate.problem.problem_id,
                candidate_vec,
                source_text=problem_embedding_text(candidate.problem),
            )
            # 회차 장부(EOS-121 B) — 이 upsert가 있어야 뒤 후보가 *이번 회차분*과 과유사로
            # 걸릴 수 있으므로, 출처 판정 재료도 정확히 이 자리에서 쌓인다.
            if round_scope is not None:
                round_scope.problem_ids.add(candidate.problem.problem_id)
        return GenerationOutcome(
            status="accepted_stored",
            candidate=candidate,
            acceptance=verdict,
            stored_problem_id=candidate.problem.problem_id,
            reasons=reasons,
        )

    # ── dry-run(저장 좌석 미주입) — 검증은 통과했으나 저장 안 함 ──
    return GenerationOutcome(
        status="accepted",
        candidate=candidate,
        acceptance=verdict,
        reasons=reasons,
    )


def run_batch(
    spec: EquivalenceSpec,
    generator: EquivalentProblemGenerator,
    n: int,
    *,
    dedup_index: ProblemEmbeddingIndex | None = None,
    embed_provider: EmbeddingProvider | None = None,
    signature_index: MutableSet[str] | None = None,
    round_scope: RoundDedupScope | None = None,
    store: ProblemBankSink | None = None,
    dedup_threshold: float = _DEFAULT_DEDUP_THRESHOLD,
    verification_tier: str | None = None,
) -> list[GenerationOutcome]:
    """생성기를 n회 돌려 각 후보의 outcome을 수집(코퍼스 배치 생성 데모).

    같은 `dedup_index`·`store`를 공유하므로 과유사 판정은 *직전까지 저장된 분에 대비* 누적으로
    걸린다 — 앞선 후보가 저장되며 그 벡터가 index에 실려, 같은 배치 안의 뒤 후보가 판박이면
    `rejected_duplicate`로 잡힌다(배치 내 중복도 차단). 생성기 소진 시 남은 회차는
    `generation_failed`(ScriptedGenerator가 None을 방출)로 정직히 기록된다.

    **구조 dedup(S2-l)은 배치에서 기본 ON**: `signature_index`를 안 주면 여기서 빈 set을 만들어
    회차 간 공유한다 — 임베딩 좌석 없이도(비용 0) 같은 방정식의 표현 변형 판박이를 결정론으로
    차단한다(Phaiakes9 실측: 같은 이차식이 문구만 바꿔 반복). 임베딩 dedup(의미 근사)과 상보.
    """
    shared_signatures: MutableSet[str] = signature_index if signature_index is not None else set()
    # 출처 판정 장부도 배치에서 **기본 ON**이다(EOS-121 B) — signature_index와 같은 이유로,
    # 좌석을 잊으면 중복 통계가 통째로 "미판정"이 되어 이 배치가 무엇 때문에 막혔는지 영영
    # 모르게 된다. 호출자가 주면 그것을 쓰고(회차 경계를 호출자가 소유하는 경우), 안 주면
    # **이 배치 1회를 한 회차로** 보고 새로 만든다(`RoundDedupScope` docstring의 수명 계약).
    shared_scope: RoundDedupScope = round_scope if round_scope is not None else RoundDedupScope()
    return [
        run_equivalent_generation(
            spec,
            generator,
            dedup_index=dedup_index,
            embed_provider=embed_provider,
            signature_index=shared_signatures,
            round_scope=shared_scope,
            store=store,
            dedup_threshold=dedup_threshold,
            verification_tier=verification_tier,
        )
        for _ in range(n)
    ]
