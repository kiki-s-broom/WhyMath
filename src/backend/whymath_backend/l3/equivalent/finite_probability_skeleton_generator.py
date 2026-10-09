"""유한 확률·경우의 수 스켈레톤 생성기 — S4-13 파일럿 저작부(결정론·LLM 0).

`RootAggregateSkeletonGenerator` 형제. 같은 `EquivalentProblemGenerator` 좌석을 구현하되
도메인이 **유한 표본공간 확률·경우의 수**다 — SymPy 대수 검산이 성립하지 않아 생성 경로가
아예 없던 영역(`problem_bank_gap_review.md` §3 D7)의 첫 실증.

**생성자 ≠ 검증자(수치 축에서도)**: 이 생성기는 답을 **닫힌 형태 조합 공식**으로 구한다
(두 주사위 합의 도수 `6-|t-7|`·이항계수 `math.comb`). 수용 게이트는 그 답을 **표본공간
전수 열거**(`l3/finite_probability`)로 다시 센다. 즉 저작 경로(공식)와 검산 경로(열거)가
서로 다른 원리다 — 생성기가 자기 계산을 자기가 확인하는 구조가 아니다(초인간 검증 S3).
공식 오적용(중복조합 오용 등)은 열거 쪽에서 재현되지 않으므로 게이트에서 `fail`로 드러난다.

**기계가 닫지 못하는 잔여**: 발문 한국어가 그 DSL 모델을 뜻하는지·등확률 가정이 서술에서
정당한지는 여기서도 게이트에서도 판정되지 않는다. 그 축은 `l3/cross_verify`(독립 다관점
LLM 교차검증) + Wilson 표본 검수 게이트가 로트 단위로 본다. 그래서 이 생성기의 산출물은
`verification_tier=machine_exhaustive`(수치 축만 증명)로 코퍼스에 명시된다.

7계층: L3 지역. schema·동일 패키지·L1 problem_bank(ConceptTag)만 import. 네트워크 0.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    GenerationType,
    LicenseType,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem
from whymath_backend.schema.provenance import ContentProvenance

__all__ = ["BAND_NAMES", "FiniteProbabilitySkeletonGenerator", "FiniteBand"]

FiniteBand = Literal["dice-sum-prob", "coin-heads-prob", "marble-all-red-prob", "dice-sum-count"]
BAND_NAMES: tuple[FiniteBand, ...] = (
    "dice-sum-prob",
    "coin-heads-prob",
    "marble-all-red-prob",
    "dice-sum-count",
)

_PROB_STANDARD = "[12확통02-01]"  # 수학적 확률
_COUNT_STANDARD = "[12확통01-01]"  # 경우의 수·순열과 조합
_PROB_CONCEPTS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통02-01", role="PRIMARY", relevance=0.95),
)
_COUNT_CONCEPTS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="H:12확통01-01", role="PRIMARY", relevance=0.95),
)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """뼈대 1개 — DSL 조건·발문·정답(닫힌 공식 산출)·해설·검산 종류."""

    band: FiniteBand
    conditions: str
    question: str
    answer: str
    explanation: str
    answer_kind: Literal["finite_probability", "finite_count"]
    answer_format: AnswerFormat
    difficulty: float
    unit_code: str
    standard_code: str
    concept_tags: tuple[ConceptTag, ...]


def _fraction_text(value: Fraction) -> str:
    """정답 문자열 — 기약분수(분모 1이면 정수). 근삿값 표기는 쓰지 않는다(정확값 계약)."""
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _probability_explanation(favorable: int, total: int) -> str:
    """해설 — 전체·유리한 경우 수와 확률. 거짓 등식이 섞이지 않게 약분 표기는 값이 다를 때만."""
    exact = Fraction(favorable, total)
    text = f"전체 경우의 수는 {total}가지이고 조건을 만족하는 경우는 {favorable}가지이다."
    if exact.denominator == total and exact.numerator == favorable:
        return f"{text} 따라서 확률은 {favorable}/{total}이다."
    return f"{text} 따라서 확률은 {favorable}/{total} = {_fraction_text(exact)}이다."


def _dice_sum_frequency(target: int) -> int:
    """두 개의 6면 주사위에서 눈의 합이 target인 경우의 수 — 닫힌 공식(열거 아님)."""
    if not 2 <= target <= 12:
        return 0
    return 6 - abs(target - 7)


def _build_pool() -> tuple[_Skeleton, ...]:
    """결정론 뼈대 풀 — 4밴드. 답은 전부 *닫힌 조합 공식*으로 구한다(검산 열거와 독립 경로)."""
    pool: list[_Skeleton] = []

    # ── 밴드 A: 두 주사위 눈의 합 확률 ──
    for target in range(2, 13):
        favorable = _dice_sum_frequency(target)
        total = 36
        pool.append(
            _Skeleton(
                band="dice-sum-prob",
                conditions=f"space=dice(n=2,faces=6); event=sum=={target}",
                question=(
                    "서로 구별되는 두 개의 주사위를 동시에 던진다. 각 주사위의 여섯 눈이 나올 "
                    f"가능성이 모두 같을 때, 나온 두 눈의 수의 합이 {target}일 확률을 "
                    "기약분수로 나타내시오."
                ),
                answer=_fraction_text(Fraction(favorable, total)),
                explanation=_probability_explanation(favorable, total),
                answer_kind="finite_probability",
                answer_format=AnswerFormat.분수,
                difficulty=2.4 + abs(target - 7) * 0.05,
                unit_code="PROB-FINITE-ENUM",
                standard_code=_PROB_STANDARD,
                concept_tags=_PROB_CONCEPTS,
            )
        )

    # ── 밴드 B: 동전 n회 중 앞면 정확히 k회 확률 ──
    for trials, heads_list in ((3, (0, 1, 2, 3)), (4, (1, 2, 3)), (5, (2, 3))):
        for heads in heads_list:
            favorable = math.comb(trials, heads)
            total = 2**trials
            pool.append(
                _Skeleton(
                    band="coin-heads-prob",
                    conditions=f"space=coin(n={trials}); event=count(H)=={heads}",
                    question=(
                        f"한 개의 동전을 {trials}번 던진다. 매번 앞면과 뒷면이 나올 가능성이 "
                        f"같을 때, 앞면이 정확히 {heads}번 나올 확률을 기약분수로 나타내시오."
                    ),
                    answer=_fraction_text(Fraction(favorable, total)),
                    explanation=_probability_explanation(favorable, total),
                    answer_kind="finite_probability",
                    answer_format=AnswerFormat.분수,
                    difficulty=2.5 + trials * 0.1,
                    unit_code="PROB-FINITE-ENUM",
                    standard_code=_PROB_STANDARD,
                    concept_tags=_PROB_CONCEPTS,
                )
            )

    # ── 밴드 C: 주머니에서 동시에 k개를 꺼내 모두 빨간 공일 확률 ──
    for red, blue, draw in ((3, 2, 2), (4, 3, 2), (5, 4, 3), (4, 4, 2), (6, 3, 3), (3, 3, 2)):
        favorable = math.comb(red, draw)
        total = math.comb(red + blue, draw)
        items = ",".join(["R"] * red + ["B"] * blue)
        pool.append(
            _Skeleton(
                band="marble-all-red-prob",
                conditions=(
                    f"space=draw(items=[{items}],k={draw},ordered=false,replace=false); "
                    f"event=count(R)=={draw}"
                ),
                question=(
                    f"주머니 안에 서로 구별되는 빨간 공 {red}개와 파란 공 {blue}개가 들어 있다. "
                    f"이 주머니에서 임의로 {draw}개의 공을 동시에 꺼낼 때, 꺼낸 공이 모두 빨간 "
                    "공일 확률을 기약분수로 나타내시오."
                ),
                answer=_fraction_text(Fraction(favorable, total)),
                explanation=_probability_explanation(favorable, total),
                answer_kind="finite_probability",
                answer_format=AnswerFormat.분수,
                difficulty=2.8 + draw * 0.1,
                unit_code="PROB-FINITE-ENUM",
                standard_code=_PROB_STANDARD,
                concept_tags=_PROB_CONCEPTS,
            )
        )

    # ── 밴드 D: 두 주사위 눈의 합이 t 이상인 경우의 수(확률이 아니라 개수) ──
    for threshold in range(4, 12):
        favorable = sum(_dice_sum_frequency(s) for s in range(threshold, 13))
        pool.append(
            _Skeleton(
                band="dice-sum-count",
                conditions=f"space=dice(n=2,faces=6); event=sum>={threshold}",
                question=(
                    "서로 구별되는 두 개의 주사위를 동시에 던진다. 나온 두 눈의 수의 합이 "
                    f"{threshold} 이상이 되는 경우의 수를 구하시오. (두 주사위는 서로 구별하며, "
                    "눈의 순서가 다르면 다른 경우로 센다.)"
                ),
                answer=str(favorable),
                explanation=(
                    f"두 주사위를 구별하여 세면 전체 경우의 수는 36가지이고, 그중 눈의 합이 "
                    f"{threshold} 이상인 경우는 {favorable}가지이다."
                ),
                answer_kind="finite_count",
                answer_format=AnswerFormat.자연수,
                difficulty=2.3 + (12 - threshold) * 0.05,
                unit_code="COUNT-FINITE-ENUM",
                standard_code=_COUNT_STANDARD,
                concept_tags=_COUNT_CONCEPTS,
            )
        )

    return tuple(pool)


@deterministic_generator
class FiniteProbabilitySkeletonGenerator:
    """유한 확률·경우의 수 생성기 — `EquivalentProblemGenerator` 좌석 구현(결정론·LLM 0).

    `band`로 뼈대 풀을 필터해 순서대로 방출한다(소진 시 None). 같은 DSL 조건이 이미 나온
    적 있으면 건너뛴다(`skip_conditions` — 배치 내 구조 중복 차단. `canonical_signature`는
    대수식 전용이라 이 도메인 DSL을 접지 못하므로 조건 문자열 자체를 키로 쓴다).
    """

    def __init__(
        self,
        *,
        band: FiniteBand,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-finite",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
    ) -> None:
        self._pool = tuple(s for s in _build_pool() if s.band == band)
        self._band = band
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — 중복 조건은 건너뛰고, 풀 소진 시 None(정직한 생성 실패)."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            if self._skip is not None and skeleton.conditions in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        """뼈대 → 후보. 저작권 메타는 구조적으로 자체생성 고정(LLM 출력 무관·재구현 0)."""
        standard_codes = sorted(spec.achievement_standard_codes) or [skeleton.standard_code]
        slug = self._stable_slug(skeleton.question, skeleton.answer, standard_codes)
        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=[skeleton.unit_code],
            difficulty_overall=round(skeleton.difficulty, 2),
            question_format=QuestionFormat.단답형,
            answer_format=skeleton.answer_format,
            achievement_standard_codes=standard_codes,
            question_text=skeleton.question,
            answer=skeleton.answer,
            answer_explanation=skeleton.explanation,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 유한 표본공간 뼈대 조립(닫힌 조합 공식으로 정답 산출)",
                    "S2-a 수용 게이트(전수 열거 검산 — 저작과 다른 원리)",
                    "독립 다관점 LLM 교차검증 표본 + Wilson 검수 게이트(잔여 서술 축)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=skeleton.conditions,
            answer_map={},  # 대수 치환맵이 없는 도메인(표본공간 DSL이 조건 그 자체)
            answer_selection=None,
            answer_aggregate=None,
            answer_kind=skeleton.answer_kind,
            solution_steps=None,
            concept_tags=list(skeleton.concept_tags),
        )

    def _stable_slug(self, question: str, answer: str, codes: Sequence[str]) -> str:
        payload = "|".join([question, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
