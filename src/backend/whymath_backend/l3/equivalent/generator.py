"""자체생성 동등문제 *생성기 좌석* — S2-d 생성부(생성기 Protocol + 결정론 자리표시자).

S2 파이프라인(S2-a 수용 게이트·S2-b 코퍼스 저장·S2-c 임베딩 dedup)을 end-to-end로 잇는
오케스트레이터(`orchestrator.py`)의 *입력측*이다. 이 모듈은 "동등문제 후보를 어떻게 만드는가"의
**좌석**만 둔다 — 실제 내용(발문·풀이·검증재료)은 정책/생성기 구현이 공급한다.

mock-first(설계 정본 미러): WH-S `ScriptedPolicy`(`whs/harness.py`)·WH-1 `ScriptedTutorPolicy`가
LLM 정책의 *자리표시자*로 결정론 시퀀스를 방출하듯, 여기 `ScriptedGenerator`는 미리 준비한
`CandidateProblem` 시퀀스를 순서대로 낸다. Kiki가 Phaiakes9 키를 열면 이 Protocol을 구현하는 실
LLM 생성기(Qwen3-Math·Claude 초안→검증)로 *교체*한다 — 오케스트레이터는 무변경(좌석 계약 동형).

7계층: 생성(=LLM 라우터 도메인)은 **L3**다. 이 좌석은 L3 안에 살며, 게이트(L3 acceptance)·저장
(L1 problem_bank)·dedup(L1 embedding)을 오케스트레이터가 조합한다(L3→L1 하향 import는 허용,
역방향 금지). 이 모듈 자체는 순수 타입·자리표시자만 담아 어떤 저장소·네트워크도 건드리지 않는다.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# ConceptTag(개념 태깅·problem_concept 적재 재료)는 S2-b L1 적재기가 소유한다 — 재구현 0으로
# 그대로 재사용한다(L3→L1 하향 import·허용). 후보가 실은 태깅을 오케스트레이터가 그대로 저장 레코드
# 로 넘긴다(같은 타입이라 변환 0).
from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.cross_verify import deterministic_author
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = [
    "DETERMINISTIC_GENERATOR_MARK",
    "CandidateProblem",
    "EquivalentProblemGenerator",
    "ScriptedGenerator",
    "deterministic_generator",
    "deterministic_generator_name",
]

# 결정론 생성기 클래스에 데코레이터가 찍는 표식 속성 — 값은 서명에 쓰인 생성기 이름이다.
# 전수 가드(`test_deterministic_author_stamp`)가 "표식 없는 생성기 = 서명 누락"을 판정한다.
DETERMINISTIC_GENERATOR_MARK = "__deterministic_generator_name__"


class CandidateProblem(BaseModel):
    """생성기가 내는 *후보 번들* — S2-a 게이트·S2-b 저장에 필요한 전부를 한 묶음으로 담는다.

    생성기는 `Problem`(본문)만 내는 게 아니라, 수용 게이트(`evaluate_equivalent_candidate`)가
    정확성·저작권을 판정하는 데 쓰는 *재료*(provenance·conditions·answer_map·solution_steps)와
    저장 시 `problem_concept`에 태깅할 개념 목록(`concept_tags`)까지 함께 낸다. 오케스트레이터는
    이 번들을 게이트→dedup→저장으로 흘려보내며 *추가 파싱·발명 없이* 필드를 그대로 소비한다.

    frozen: 후보는 생성 시점에 확정된 불변 값이다(파이프라인이 변형하지 않음).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem: Problem = Field(description="후보 문제 본문(자체생성·WHYMATH_GENERATED).")
    provenance: ContentProvenance = Field(
        description="저작권 이력 — 게이트 저작권 게이트(값 확인)·저장 provenance 메타 재료.",
    )
    conditions: str | list[str] = Field(
        description="답 검산용 원 조건(발문 파싱 밖·호출자 제공) — 게이트 정확성 Tier1 재료.",
    )
    answer_map: dict[str, str] = Field(
        default_factory=dict,
        description="조건 치환맵({변수: 값}) — 게이트 정확성 Tier1 재료.",
    )
    answer_selection: str | None = Field(
        default=None,
        description=(
            "(선택·S2-i) 근 선택 — largest(큰 근)/smallest(작은 근)/unique(유일). '큰 근을 "
            "구하시오'류는 방정식만으론 답이 유일하지 않아 게이트가 *어느 근인가*를 검증하는 데 "
            "쓴다. None=선택 요구 없음(다근이면 게이트가 유일성 미확정으로 강등)."
        ),
    )
    answer_aggregate: str | None = Field(
        default=None,
        description=(
            '(선택·S2 킬러) 근 집계 검증 종류 — "sum"(근의 합)/"product"(근의 곱). 설정 시 '
            "게이트가 answer(주장 집계값)를 verify_root_aggregate로 검증한다(답이 근이 아니라 "
            "근들의 합/곱인 킬러 문항). None=일반(답이 근)."
        ),
    )
    answer_kind: str | None = Field(
        default=None,
        description=(
            '(선택·개념형) 개수 검증 종류 — "real_root_count"(실근 개수)/"extremum_count"(극값 '
            "개수). 설정 시 게이트가 answer(주장 개수)를 SymPy로 독립 계산해 검증한다(답이 값이 "
            "아니라 개수인 개념형 문항). None=일반."
        ),
    )
    solution_steps: list[str] | None = Field(
        default=None,
        description="(선택) 분해된 풀이 단계 — 게이트 정확성 Tier2(단계 동치) 재료. None=미제공.",
    )
    concept_tags: list[ConceptTag] = Field(
        default_factory=list,
        description=(
            "개념 태깅(problem_concept 적재용) — 각 원소 (concept_src_id·role·relevance). S2-b "
            "적재기의 `ConceptTag`를 그대로 재사용(변환 0). 저장 시 concept_src_id→concept_id 해석."
        ),
    )
    authored_by: str | None = Field(
        default=None,
        description=(
            "(선택·PB-15) 저작 주체 서명 — LLM 생성기는 `llm:<모델 id>`"
            "(`cross_verify.llm_author`)를, 결정론 생성기는 `@deterministic_generator`가 "
            "`deterministic:<생성기>`(`cross_verify.deterministic_author`)를 찍는다(PB-17). "
            "None=기록 없음(스크립트 생성기·서명 해석 실패) — 교차검증 가드는 기록 없는 대상을 "
            "독립성 입증 불가로 거부한다(fail-closed)."
        ),
    )


_GeneratorT = TypeVar("_GeneratorT", bound=type[Any])


def deterministic_generator_name(cls: type[Any]) -> str:
    """결정론 생성기의 서명 이름 — 정의 모듈 파일명(`binomial_distribution_skeleton_generator`).

    한 모듈에 생성기 클래스가 여럿이어도(예 `calculus_skeleton_generator`) 이름은 모듈 단위다.
    기존 코퍼스 백필(`problem_corpus_author_backfill`)이 `_provenance.json`의
    `generation_method`에 적힌 생성기 *파일명*에서 도출하는 서명과 같은 형식이다.
    """
    return cls.__module__.rsplit(".", 1)[-1]


def deterministic_generator(cls: _GeneratorT) -> _GeneratorT:
    """결정론 생성기 클래스 데코레이터 — `generate()`가 낸 후보에 `deterministic:<생성기>` 서명.

    PB-17: 서명은 생성 시점에 *생성기 자신*이 찍는다(사후에 사람이 선언하지 않는다). 후보가 이미
    `authored_by`를 갖고 있으면 그대로 둔다(덮어쓰지 않는다). 생성 실패(None)는 그대로 통과한다.
    클래스 본문에 `generate`가 직접 정의돼 있어야 한다 — 상속받은 메서드만 있으면 서명할 지점이
    어디인지 모호하므로 데코레이트 시점에 거부한다.
    """
    original = cls.__dict__.get("generate")
    if original is None:
        raise TypeError(f"{cls.__name__}: generate()가 클래스 본문에 없어 서명을 찍을 수 없다")
    name = deterministic_generator_name(cls)
    signature = deterministic_author(name)

    @functools.wraps(original)
    def generate(self: Any, spec: EquivalenceSpec) -> CandidateProblem | None:
        candidate: CandidateProblem | None = original(self, spec)
        if candidate is None or candidate.authored_by is not None:
            return candidate
        return candidate.model_copy(update={"authored_by": signature})

    setattr(cls, "generate", generate)  # noqa: B010 — 제네릭 클래스 타입에 속성을 심는다.
    setattr(cls, DETERMINISTIC_GENERATOR_MARK, name)  # noqa: B010
    return cls


@runtime_checkable
class EquivalentProblemGenerator(Protocol):
    """동등문제 생성기 좌석 — 명세(`EquivalenceSpec`)를 받아 후보 1건을 낸다(실패=None).

    프로덕션=LLM 생성기(Qwen3-Math 초안→Claude 검증·Phaiakes9)·테스트/데모=`ScriptedGenerator`.
    오케스트레이터는 이 좌석이 낸 후보를 *신뢰하지 않고* S2-a 게이트로 검증한 뒤에야 저장한다
    (WH-S 하네스가 정책 추론을 verify로 검증하는 것과 동형). `generate`가 None이면 생성 실패다
    (프롬프트 미충족·모델 거부 등) — 오케스트레이터가 `generation_failed`로 정직히 기록한다.
    """

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """명세에 맞는 동등문제 후보 1건을 생성(실패 시 None)."""
        ...


class ScriptedGenerator:
    """결정론 생성기 — 준비한 `CandidateProblem` 시퀀스를 순서대로 방출(테스트·데모·자리표시자).

    LLM 생성기의 *자리표시자*다(WH-S `ScriptedPolicy` 미러). 시퀀스가 소진되면 `None`(생성 실패)을
    돌려줘 배치 러너가 안전 종료하게 한다. 시퀀스 원소로 `None`을 섞으면 특정 위치의 생성 실패도
    결정론적으로 재현할 수 있다(파이프라인 `generation_failed` 분기 테스트).
    """

    def __init__(self, candidates: Sequence[CandidateProblem | None]) -> None:
        self._candidates: list[CandidateProblem | None] = list(candidates)
        self._index = 0

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 후보를 방출(소진 시 None) — spec은 무시(스크립트가 이미 후보를 확정)."""
        del spec  # 스크립트 생성기는 명세에 반응하지 않는다(미리 확정된 후보를 재생).
        if self._index >= len(self._candidates):
            return None
        candidate = self._candidates[self._index]
        self._index += 1
        return candidate
