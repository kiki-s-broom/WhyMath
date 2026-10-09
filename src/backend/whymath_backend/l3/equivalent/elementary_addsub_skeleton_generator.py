"""초등 두 자리 수 덧셈·뺄셈 파라메트릭 스켈레톤 생성기 — W2 초등 축 최초 생성기(결정론·LLM 0).

학년축 최단경로 계획(`docs/strategy/grade_axis_mvp_shortest_path_v1.md`) §3 W2. 실측
(2026-08-05): 기존 12개 스켈레톤 생성기(`skeleton_generator.py` 이차방정식·`calculus_*`·
`exp_log_*`·`trig_*`·`sequence_*`·`root_aggregate_*`·`finite_probability_*` 등)는 전부
고등학교 교육과정 개념이다 — 초등 축(성취기준 커버율 4.1%·0커버 116건, 4축 중 최대 공백)에는
재사용 가능한 생성기가 하나도 없었다. 이 모듈이 그 공백의 첫 조각을 메운다.

`SkeletonEquivalentProblemGenerator`(이차방정식)와 **동일한 좌석**(`EquivalentProblemGenerator`
Protocol)·**동일한 수용 게이트**(`evaluate_equivalent_candidate`, `l3/verify_answer` 경유)를
그대로 쓴다 — 신규 게이트 발명 0. Tier1(`l3/verify_answer`)은 방정식 sympify 기반 범용
검산기라 조건 `"34 + 27 = x"`(초등 산술)도 이차방정식과 동일 경로로 검증된다(도메인 전용
검증기 신설 불요 — 2026-08-05 실측 확인).

대상 성취기준: `[2수01-06]`(두 자리 수의 덧셈과 뺄셈, 초등학교 1~2학년군, 2022 개정). 개념그래프
매핑: `math.addition.du-jari-deotsem-ppaelsem`(source_id="A2", 개념그래프 코퍼스 조회로 확인 —
이 모듈 자체는 그 코퍼스를 읽지 않는다·quadratic 생성기의 "HK06" 하드코딩과 동일 패턴).

범위(v1): 두 자리 수(11~89) ± 두 자리 수. 뺄셈은 피감수 ≥ 감수만(음수 답 제외 — 자연수 범위
성취기준과 정합). 난이도는 받아올림/받아내림 유무에서 결정론 추정한다(받아올림·받아내림이
있으면 인지 부하가 커진다는 통설 — L6 밴드 앵커(`_DEPTH_TARGET_DIFFICULTY` awareness=1.5)
이내로 클램프해 4축 확장이 고등 밴드로 새어나가지 않게 한다).

발문 서너 종을 회전한다(표면 변주). 조사(을/를·와/과)는 수 읽기 기반 판별기(`josa.py`)를
재사용한다 — 하드코딩 금지(이차방정식 생성기와 동일 원칙).

**노출 게이팅**: 이 생성기가 낸 문항은 수용 게이트(SymPy Tier1) 통과가 곧 "수치 정확"을
의미할 뿐, "AI 검수"(초인간 검증 §2 S5 Wilson 게이트)는 별도다 — 그 단계는 실 LLM 호출이
필요해 이 저장소의 원격 실행 환경 밖(Kiki 머신)에서만 가능하다(CLAUDE.md 검증 권위 서열).
따라서 이 생성기의 산출물은 항상 `problem_bank_*_v0`(v0=사람 검수 전) 코퍼스로만 나가고,
`is_published=False` 상태로 노출 게이팅 전까지 유지한다(`problem_bank_probability_finite_v0`
선례와 동일 원칙).

7계층: L3(생성=LLM 라우터 도메인이나 이 구현은 LLM 0 — 좌석 계약만 공유). schema(최하위)·
동일 패키지(canonicalize 불필요 — 조건 dedup은 `finite_probability_skeleton_generator` 선례를
따라 원시 조건 문자열 집합으로 한다, 사유는 아래 `ElementaryAddSubSkeletonGenerator` 참조).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal

from whymath_backend.l1.problem_bank.populate import ConceptTag
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem, deterministic_generator
from whymath_backend.lang.josa import eul_reul, wa_gwa
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

__all__ = ["ElementaryAddSubSkeletonGenerator", "Operation"]

# 개념그래프 매핑(모듈 docstring) — 덧셈·뺄셈이 같은 성취기준·같은 개념 노드를 공유한다
# (2022 개정 [2수01-06] "두 자리 수의 덧셈과 뺄셈"이 한 성취기준에 두 연산을 함께 담음).
_DEFAULT_CONCEPT_TAGS: tuple[ConceptTag, ...] = (
    ConceptTag(concept_src_id="A2", role="PRIMARY", relevance=0.95),
)

# 두 자리 수 범위 — 성취기준 "두 자리 수의 범위" 그대로(10~99, 실제 풀은 11~89로 한 자리 경계
# 여유를 둬 받아올림/받아내림 조합이 자연스럽게 나오게 한다).
_OPERAND_MIN, _OPERAND_MAX = 11, 89
_STEP = 3  # 풀 크기 조절(전수 아님 — 5주 pairs 격자 subsample, 900+문항 규모면 충분한 다양성)

Operation = Literal["add", "subtract"]

# 발문 템플릿(회전) — {a}{wa}·{b}{eul}은 조사 판별기(josa.py) 치환 자리, 하드코딩 없음.
_ADD_TEMPLATES: tuple[str, ...] = (
    "다음을 계산하시오: {a} + {b}",
    "{a}{wa} {b}의 합을 구하시오.",
    "{a}에 {b}{eul} 더하면 얼마입니까?",
)
_SUB_TEMPLATES: tuple[str, ...] = (
    "다음을 계산하시오: {a} - {b}",
    "{a}에서 {b}{eul} 뺀 값을 구하시오.",
    "{a}{wa} {b}의 차를 구하시오.",
)


@dataclass(frozen=True, slots=True)
class _Skeleton:
    """문제 뼈대 — (피연산자 a·b·연산). 모든 수치의 단일 진실 원천."""

    a: int
    b: int
    operation: Operation

    @property
    def result(self) -> int:
        return self.a + self.b if self.operation == "add" else self.a - self.b

    @property
    def carries_or_borrows(self) -> bool:
        """받아올림(덧셈)/받아내림(뺄셈) 발생 여부 — 난이도 추정의 유일 신호."""
        if self.operation == "add":
            return (self.a % 10) + (self.b % 10) >= 10
        return (self.a % 10) < (self.b % 10)

    @property
    def difficulty(self) -> float:
        """rule-based 난이도 — 받아올림/받아내림 있으면 +0.4(awareness~procedural 초입 유지).

        L6 밴드 앵커(`_DEPTH_TARGET_DIFFICULTY`: awareness=1.5)를 넘지 않게 클램프해, 초등
        1~2학년군 콘텐츠가 실수로 고학년 밴드에 새어들지 않게 한다(4축 확장이 학년별 깊이
        분리를 흐리면 안 된다 — 학년축 최단경로 계획 §2.1 오버레이 원칙과 동형 방어).
        """
        base = 1.2 + (0.4 if self.carries_or_borrows else 0.0)
        return min(base, 1.5)


def _build_pool() -> tuple[_Skeleton, ...]:
    """덧셈·뺄셈 뼈대 풀 — 격자 subsample 후 고정 시드 셔플(재현·디버그)."""
    pool: list[_Skeleton] = []
    for a in range(_OPERAND_MIN, _OPERAND_MAX + 1, _STEP):
        for b in range(_OPERAND_MIN, _OPERAND_MAX + 1, _STEP):
            if a >= b:  # 덧셈 a+b=b+a 대칭 중복 제거(a>=b만 수록)
                pool.append(_Skeleton(a=a, b=b, operation="add"))
            if a > b:  # 뺄셈은 답이 양의 자연수일 때만(a==b는 답 0 — KR 초등 자연수 관례 밖 제외)
                pool.append(_Skeleton(a=a, b=b, operation="subtract"))
    random.Random(20260805).shuffle(pool)
    return tuple(pool)


@deterministic_generator
class ElementaryAddSubSkeletonGenerator:
    """결정론 스켈레톤 생성기 — 초등 두 자리 수 덧셈·뺄셈(`EquivalentProblemGenerator` 좌석).

    풀을 순서대로 소비하며 후보를 낸다(소진 시 None — 오케스트레이터가 `generation_failed`로
    정직 기록). `skip_conditions`에 이미 코퍼스에 있는 조건 문자열 집합을 주면 해당 뼈대를
    건너뛴다 — `FiniteProbabilitySkeletonGenerator` 선례와 동일 관례(이 도메인의 조건은
    `canonical_signature`가 설계 대상으로 삼은 다항방정식이 아니라 단순 산술식이라, 정규화
    불가 시 None을 반환할 위험을 감수하기보다 원시 문자열 dedup을 그대로 쓴다 — 보수적 선택).
    """

    def __init__(
        self,
        *,
        operation: Operation | None = None,
        skip_conditions: AbstractSet[str] | None = None,
        slug_prefix: str = "wm-elem-addsub",
        subject: Subject = Subject.공통,
        curriculum_version: Curriculum = Curriculum.REVISION_2022,
        valid_from_year: int = 2022,
        unit_codes: Sequence[str] = ("ELEM-ADDSUB-2DIGIT",),
        concept_tags: Sequence[ConceptTag] = _DEFAULT_CONCEPT_TAGS,
    ) -> None:
        # `operation` 필터(`SkeletonEquivalentProblemGenerator`의 `variant` 필터 선례 미러) —
        # 미지정이면 덧셈·뺄셈 혼합 풀 전체를 순서대로 낸다. 배치가 밴드를 나누려면 *반드시*
        # 이 필터로 인스턴스를 분리해야 한다: `_build_pool()`은 고정 시드라 필터 없이 별도
        # 인스턴스를 여러 개 만들면 매번 *같은* 셔플 순서를 재생해 같은 뼈대가 중복 방출된다
        # (2026-08-05 실측 사고 — 최초 배치가 이 함정에 빠져 "덧셈 밴드"·"뺄셈 밴드"가 실제로는
        # 같은 혼합 뼈대를 두 번씩 낸 것으로 드러남 — `harness/elementary_addsub_batch.py`
        # 수정 참조).
        full_pool = _build_pool()
        self._pool = (
            full_pool
            if operation is None
            else tuple(s for s in full_pool if s.operation == operation)
        )
        self._index = 0
        self._skip = skip_conditions
        self._slug_prefix = slug_prefix
        self._subject = subject
        self._curriculum_version = curriculum_version
        self._valid_from_year = valid_from_year
        self._unit_codes = list(unit_codes)
        self._concept_tags = list(concept_tags)

    # ── EquivalentProblemGenerator 좌석 ────────────────────────────────
    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        """다음 뼈대를 후보로 조립 — skip 집합에 있는 조건은 건너뛰고, 풀 소진 시 None."""
        while self._index < len(self._pool):
            skeleton = self._pool[self._index]
            self._index += 1
            condition = self._condition(skeleton)
            if self._skip is not None and condition in self._skip:
                continue
            return self._assemble(spec, skeleton)
        return None

    # ── 조립(전부 결정론·수치의 단일 진실 원천은 뼈대) ─────────────────
    @staticmethod
    def _condition(skeleton: _Skeleton) -> str:
        op = "+" if skeleton.operation == "add" else "-"
        return f"{skeleton.a} {op} {skeleton.b} = x"

    def _assemble(self, spec: EquivalenceSpec, skeleton: _Skeleton) -> CandidateProblem:
        templates = _ADD_TEMPLATES if skeleton.operation == "add" else _SUB_TEMPLATES
        question_text = templates[self._index % len(templates)].format(
            a=skeleton.a,
            b=skeleton.b,
            wa=wa_gwa(str(skeleton.a)),
            eul=eul_reul(str(skeleton.b)),
        )
        answer_text = str(skeleton.result)
        op_word = "더하면" if skeleton.operation == "add" else "빼면"
        explanation = (
            f"{skeleton.a}{wa_gwa(str(skeleton.a))} {skeleton.b}{eul_reul(str(skeleton.b))} "
            f"{op_word} {answer_text}이다."
        )
        condition = self._condition(skeleton)
        standard_codes = sorted(spec.achievement_standard_codes)
        slug = self._stable_slug(question_text, answer_text, standard_codes)

        problem = Problem(
            problem_id=uuid.uuid5(uuid.NAMESPACE_URL, f"whymath:problem:{slug}"),
            slug=slug,
            source_type=SourceType.자체생성,
            curriculum_version=self._curriculum_version,
            valid_from_year=self._valid_from_year,
            subject=self._subject,
            unit_codes=list(self._unit_codes),
            difficulty_overall=skeleton.difficulty,
            question_format=QuestionFormat.단답형,
            answer_format=AnswerFormat.자연수,
            achievement_standard_codes=standard_codes,
            question_text=question_text,
            choices=None,
            answer=answer_text,
            answer_explanation=explanation,
            distractor_map=None,
        )
        provenance = ContentProvenance(
            generation_type=GenerationType.FULLY_GENERATED,
            license=LicenseType.WHYMATH_GENERATED,
            original_source=None,
            transformation_pipeline={
                "steps": [
                    "결정론 스켈레톤 조립(피연산자→식 역산·W2)",
                    "S2-a 수용 게이트(Tier1 산술 검산)",
                    "AI 검수 게이트 대기(Kiki 머신·실 LLM 필요 — 미통과 시 is_published=False)",
                ],
            },
        )
        return CandidateProblem(
            problem=problem,
            provenance=provenance,
            conditions=condition,
            answer_map={"x": answer_text},
            # solution_steps는 Tier2(단계 동치) 검증 재료다 — `answer_explanation`의 한국어
            # 산문은 검증 가능한 expr_before/expr_after 쌍이 아니라 여기 넣으면 게이트가 "0
            # 검증·0 미검증"으로 걸려 정직하게 unverified 강등된다(실측 확인). 한 자릿수 연산
            # 하나짜리 산술은 애초에 다단계 과정이 없다 — Tier1(수치 검산) 단독으로 충분하고
            # 정직하다(단계 없음 경로 = Tier1 pass만으로 verified).
            solution_steps=None,
            concept_tags=list(self._concept_tags),
        )

    def _stable_slug(self, question_text: str, answer: str, codes: Sequence[str]) -> str:
        """결정론 안정 slug — 내용 해시(멱등 upsert 키·skeleton_generator 규약 미러)."""
        payload = "|".join([question_text, answer, ",".join(sorted(codes))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self._slug_prefix}-{digest}"
