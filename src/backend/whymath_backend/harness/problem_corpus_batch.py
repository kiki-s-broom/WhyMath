"""동등문제 스켈레톤 코퍼스 배치 CLI — S2-p *조성 루트*(ops·JSONL 산출).

Phaiakes9 전용이던 배치 스크립트(run_batch_corpus.py·repo 밖)를 **repo 버전 CLI**로 승격한다.
스켈레톤 파이프라인은 LLM 0·DB 0·순수 결정론이라 어디서든 같은 산출물이 나온다 — 생성 코퍼스
(`data/corpus/problem_bank_generated_v0/problems.jsonl`)를 재현 가능하게 전면 재생성하는 것이
이 CLI의 존재 이유다.

사용법:
    python -m whymath_backend.harness.problem_corpus_batch \\
        [--out <jsonl>] [--short 90] [--mc 45] [--sqrt 30] [--sqrt-mc 20]
        [--calc-extremum 40] [--calc-tangent 40] [--calc-value 40] [--exp 25] [--log 20]
        [--arith 60] [--geo 30] [--trig 13] [--seq-inductive 30] [--dry-run]

동작: 문제군별 밴드를 순차 실행 → 전 후보가 S2-a 4종 게이트를 통과해야 sink에 실린다 → JSONL로
기록. **quad 문제군**(short/mc/sqrt/sqrt_mc·이차방정식 근)은 공유 signature_index로 겹침을 차단하고,
**calc 문제군**(calc-extremum=삼차 극값 x좌표·calc-tangent=삼차 접선 기울기 m인 점의 x좌표·
calc-value=삼차 극댓값·극솟값(값), 셋 다 미적분Ⅰ)은 군마다 별도 signature_index다(conditions가
도함수/극값 이차방정식이라 이차방정식과 구조 동형 → 공유 시 거짓 cross-군 dedup). 리포트를 JSON으로
stdout에 내고, **수율 미달이면 종료 코드 1**(조용한 실패 금지 — 밴드별 사유 포함).

조성 루트 소관(주입 원칙): 객관식 distractor의 오개념/op-code id는 여기서 L4 정본
(`CATALOG_BY_ID`·`DISTRACTOR_BY_ID`)을 읽어 L3 생성기에 *주입*한다 — L3 코드에는 L4 import·id
하드코딩이 없다(CLAUDE.md 오개념 독립 DB·계층 규칙). harness는 import-linter 계약 밖(상위 계층
호출이 정상인 조성/ops 층 — `agreement_gate_cli` 선례).

결정론 보장(재실행 바이트 동일): LLM 0·DB 0·타임스탬프 0·slug 기반 uuid5 problem_id·고정 시드
풀·값 정렬 선지 — 같은 인자로 두 번 실행하면 산출 파일이 바이트까지 같다(테스트 봉인). 산출물은
v0(사람 검수 전) — 게이트 통과 ≠ 학생 노출(§03 정본).

시그니처 태깅(S2-06): sink 기록 직전 전 레코드에 `l1/problem_bank/signature_tagger.
apply_signatures`를 적용한다 — 태거가 시그니처의 단일 권위(생성기는 빈 배열)다. 규칙 미해당
레코드는 원본 객체 그대로라(멱등) 기존 문항의 직렬화 바이트가 불변이다(비날조 원칙).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, MutableSet, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from whymath_backend.harness.needs_review_worklist import (
    build_worklist,
    render_worklist_markdown,
)
from whymath_backend.l1.problem_bank.populate import (
    ProblemBankPopulateReport,
    ProblemBankRecord,
    ProblemRelationTag,
)
from whymath_backend.l1.problem_bank.signature_tagger import apply_signatures
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.calculus_skeleton_generator import (
    CalculusExtremumMCSkeletonGenerator,
    CalculusExtremumSkeletonGenerator,
    CalculusExtremumValueSkeletonGenerator,
    CalculusIrrationalExtremumSkeletonGenerator,
    CalculusTangentSlopeSkeletonGenerator,
)
from whymath_backend.l3.equivalent.exp_log_skeleton_generator import (
    ExponentialEquationSkeletonGenerator,
    LogarithmicEquationSkeletonGenerator,
)
from whymath_backend.l3.equivalent.generator import EquivalentProblemGenerator
from whymath_backend.l3.equivalent.inductive_sequence_skeleton_generator import (
    InductiveSequenceSkeletonGenerator,
)
from whymath_backend.l3.equivalent.orchestrator import (
    GenerationOutcome,
    ProblemBankSink,
)
from whymath_backend.l3.equivalent.orchestrator import (
    run_batch as _orchestrator_run_batch,
)
from whymath_backend.l3.equivalent.sequence_skeleton_generator import (
    ArithmeticSequenceSkeletonGenerator,
    GeometricSequenceSkeletonGenerator,
)
from whymath_backend.l3.equivalent.sequence_sum_skeleton_generator import (
    ArithmeticSumSkeletonGenerator,
    GeometricSumSkeletonGenerator,
)
from whymath_backend.l3.equivalent.skeleton_generator import (
    GeneratorVariant,
    SkeletonEquivalentProblemGenerator,
)
from whymath_backend.l3.equivalent.trig_equation_skeleton_generator import (
    TrigonometricEquationSkeletonGenerator,
)
from whymath_backend.l3.equivalent.trig_skeleton_generator import (
    TrigonometricValueSkeletonGenerator,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.distractor import DISTRACTOR_BY_ID

__all__ = [
    "CorpusBatchReport",
    "JsonlCorpusSink",
    "build_distractor_codes",
    "main",
    "run_corpus_batch",
]

# 밴드 공통 스펙 — 현 스켈레톤 풀(이차방정식 두 근 계산·대소 비교)의 성취기준.
# S3-15 성취기준 재태깅(감사 확정 — root_aggregate_batch.py Vieta 밴드 S3-12 선례 동형):
# 종전 [10공수1-02-02](판별식으로 근을 "판별") 하드코딩은 오귀속 — 이 풀은 판별식을 쓰지
# 않고 인수분해·완전제곱꼴로 근을 직접 "계산"한다. 정본 statement 대조로 [9수02-20]
# ("이차방정식을 풀 수 있고, 이를 활용하여 문제를 해결할 수 있다")이 정위치다.
# 난이도 2.5 고정: 추정 난이도(2.0~3.6) 최대 gap 1.1 < 3.5(게이트 감쇠 수학)라 밴드 분리 불요.
_STANDARD_CODE = "[9수02-20]"
_SPEC_DIFFICULTY = 2.5

# 객관식 distractor 주입쌍 — L4 정본 id(오개념·op-code). 여기 *조성 루트*에만 존재한다.
_MC_INJECTION: dict[str, tuple[str, str]] = {
    "opposite_root": ("opposite-root-selected", "select-opposite-root"),
    "sign_flip": ("factor-sign-flip", "factor-sign-flip-root"),
}

# 극값 MC distractor 주입쌍(삼차 극값 객관식) — 정답 아닌 극값=극대극소 혼동·극점 x좌표=값↔좌표.
# 키는 CalculusExtremumMCSkeletonGenerator가 기대하는 주입 키(max_min·value_vs_point)와 정합.
_CALC_MC_INJECTION: dict[str, tuple[str, str]] = {
    "max_min": ("extremum-max-min-confused", "select-opposite-extremum"),
    "value_vs_point": ("extremum-value-vs-point-confused", "report-x-coordinate-for-value"),
}

# 밴드 기본 크기 — quad 185 + calc 120 + calc-value-mc 30 + calc-extremum-irr 30 + exp 25 + log 20
# + 수열항 90 + 삼각값 13 + 수열합 65 + 삼각방정식 12 + 귀납수열 30 = 총 620건(CI 봉인 ≥100 여유).
# 풀 실측: short 443·mc 159·sqrt 122·sqrt_mc 58·calc-extremum 162·calc-tangent 162·calc-value 150·
# calc-value-mc 146·calc-extremum-irr 180·exp 28·log 28·arith 90·geo 45·trig 13·
# arith-sum 261·geo-sum 58·trig-eq 18·seq-inductive 98.
_DEFAULT_SHORT_N = 90
_DEFAULT_MC_N = 45
_DEFAULT_SQRT_N = 30
_DEFAULT_SQRT_MC_N = 20
_DEFAULT_CALC_EXTREMUM_N = 40
_DEFAULT_CALC_TANGENT_N = 40
_DEFAULT_CALC_VALUE_N = 40
_DEFAULT_CALC_VALUE_MC_N = 30
_DEFAULT_CALC_EXTREMUM_IRR_N = 30
_DEFAULT_EXP_N = 25
_DEFAULT_LOG_N = 20
_DEFAULT_ARITH_N = 60
_DEFAULT_GEO_N = 30
_DEFAULT_TRIG_N = 13
_DEFAULT_ARITH_SUM_N = 45
_DEFAULT_GEO_SUM_N = 20
_DEFAULT_TRIG_EQ_N = 12
_DEFAULT_SEQ_INDUCTIVE_N = 30

# 미적분(극값) 밴드 스펙 — 별도 성취기준([12미적Ⅰ-02-07]·함수의 증가·감소와 극대·극소).
# 난이도 3.3 고정: 극값 추정(3.0~4.0) 최대 gap 0.7 < 3.5(게이트 감쇠 수학)라 안전.
# **별도 signature_index 사용**: 극값 conditions는 *도함수 방정식*이라 구조가 이차방정식과
# 동형이다 — quad 밴드와 index를 공유하면 도함수 방정식이 quad 문제 방정식과 우연히 같을 때
# (같은 선택) 거짓 dedup으로 다른 문제군을 중복 처리한다. 문제군이 다르므로 dedup도 군 내부로.
_CALC_STANDARD_CODE = "[12미적Ⅰ-02-07]"
_CALC_SPEC_DIFFICULTY = 3.3

# 미적분(접선 기울기) 밴드 스펙 — 미분계수([12미적Ⅰ-02-01]·미분계수=접선 기울기). f'(x)=m의 근
# 계열이라 conditions도 도함수 방정식(이차 동형) → 극값과도 cross-군 충돌 가능 → **또 별도 index**.
_TANGENT_STANDARD_CODE = "[12미적Ⅰ-02-01]"
_TANGENT_SPEC_DIFFICULTY = 3.3

# 미적분(극값의 값) 밴드 스펙 — 극값 x좌표와 *같은* 성취기준([12미적Ⅰ-02-07]·극대·극소)·개념.
# conditions는 두 극값의 이차방정식(dummy x)이라 극값 x좌표·접선 방정식과 구조 동형 → 또 cross-군
# 오dedup 위험(극값 x=1,3의 조건과 극값 값이 1,3인 조건이 canonical 동일) → **또 별도 index**.
_VALUE_STANDARD_CODE = "[12미적Ⅰ-02-07]"
_VALUE_SPEC_DIFFICULTY = 3.3

# 미적분(극값의 값) 객관식 밴드 스펙 — 극값 값과 동일 성취기준·개념([12미적Ⅰ-02-07]·극대·극소).
# conditions는 극값 쌍 이차방정식(값 밴드와 동형)이라 또 cross-군 오dedup 위험 → **또 별도 index**.
# 오답 선지 오개념 2종(극대극소 혼동·값↔x좌표 혼동)을 주입하므로 target_misconception_ids도 2종.
_VALUE_MC_STANDARD_CODE = "[12미적Ⅰ-02-07]"
_VALUE_MC_SPEC_DIFFICULTY = 3.3

# 미적분(무리 임계점 극값) 밴드 스펙 — 극값 x좌표와 *같은* 성취기준([12미적Ⅰ-02-07]·극대·극소).
# conditions는 도함수 monic 이차방정식이나 판별식이 비제곱이라 정수 극값 밴드와 근의 체가 달라
# canonical signature가 애초 서로소지만, calc 규약대로 **또 별도 index**(오dedup 이중 방어).
# 난이도 3.5 고정: 무리 극값 추정({3.5, 3.8}) 최대 gap 0.3 < 0.5(tol) → 난이도 성분 만점.
_IRR_STANDARD_CODE = "[12미적Ⅰ-02-07]"
_IRR_SPEC_DIFFICULTY = 3.5

# 지수·로그 밴드 스펙 — 대수(고2·[12대수01-08]·지수함수·로그함수 활용). conditions가 비다항
# (b**x-v·log(x,b)-k)이라 canonical signature=None → signature_index 무의미(풀 결정론 유일이라
# dedup 불요)·quad/calc(다항 signature)와 cross-군 충돌 원천 불가. 난이도 3.0: 추정(2.6~3.4)
# 최대 gap 0.4 < 0.5(tol)이라 동등성 난이도 성분 만점.
_EXPLOG_STANDARD_CODE = "[12대수01-08]"
_EXPLOG_SPEC_DIFFICULTY = 3.0

# 수열·삼각 밴드 스펙 — 대수(고2) 성취기준. conditions는 `x − 상수`(일반항 계산식·특수각 값)이라
# **다항 signature(非None)**이지만, 각 생성기 풀이 답/값 기준 dedup돼 밴드 내 signature가 전건
# 유일하다(오dedup 0). 각 밴드는 **별도 signature_index**(문제군 분리·cross-군 오dedup 방지·calc
# 패턴 미러). 난이도: 등차 3.0(추정 2.7~3.2)·등비 3.2(3.0~3.5)·삼각 3.0(2.8~3.3), gap ≤ 0.3 < tol.
_ARITH_STANDARD_CODE = "[12대수03-02]"
_ARITH_SPEC_DIFFICULTY = 3.0
_GEO_STANDARD_CODE = "[12대수03-03]"
_GEO_SPEC_DIFFICULTY = 3.2
_TRIG_STANDARD_CODE = "[12대수02-02]"
_TRIG_SPEC_DIFFICULTY = 3.0

# 수열합·삼각방정식 밴드 스펙 — 일반항·특수각값 형제와 같은 성취기준(도메인 분담). 등차·등비합은
# conditions `x − (합 공식)`이라 **다항 signature(非None)**·답 dedup으로 밴드 내 유일; 삼각방정식은
# 초월함수라 **signature=None**(exp/log형·slug 유일성에 위임). 각 밴드 **별도 index**(문제군 분리·
# calc 패턴 미러). 난이도: 등차합 3.2(추정 3.0~3.4)·등비합 3.3(3.2~3.5)·삼각방정식 3.3(3.2~3.5),
# 최대 gap ≤ 0.2 < 0.5(tol) → 동등성 난이도 성분 만점.
_ARITH_SUM_STANDARD_CODE = "[12대수03-02]"
_ARITH_SUM_SPEC_DIFFICULTY = 3.2
_GEO_SUM_STANDARD_CODE = "[12대수03-03]"
_GEO_SUM_SPEC_DIFFICULTY = 3.3
_TRIG_EQ_STANDARD_CODE = "[12대수02-02]"
_TRIG_EQ_SPEC_DIFFICULTY = 3.3

# 귀납 정의 수열 밴드 스펙(S2-06) — 수열의 귀납적 정의([12대수03-06]·`standards_v1` 실재 고시코드).
# conditions는 점화식 폐형 `x − 상수`(다항 signature 非None)·답 dedup(등차·등비 가로질러)으로 밴드
# 내 유일 — **별도 signature_index**(문제군 분리·calc 패턴 미러). 난이도 3.4 고정: rule-based
# 추정(3.3~3.5) 최대 gap 0.1 < 0.5(tol) → 동등성 난이도 성분 만점. 이 밴드가 시그니처 태거(T1
# 조건 나열·T2 점화식)의 실제 양성 코퍼스다 — 기존 문항 날조 없이 수능 신호를 점화한다.
_INDSEQ_STANDARD_CODE = "[12대수03-06]"
_INDSEQ_SPEC_DIFFICULTY = 3.4


def _default_out_path() -> Path:
    """기본 산출 경로 — repo의 생성 코퍼스 v0(경로 유지 전면 교체·품질 테스트와 동일 규약).

    `__file__` = <repo>/src/backend/whymath_backend/harness/problem_corpus_batch.py 라
    parents[4]가 repo 루트다(harness→whymath_backend→backend→src→repo — 실측 확인). editable
    설치(개발 트리) 전제의 ops CLI — 배포 트리에선 `--out`으로 명시한다.
    """
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "data" / "corpus" / "problem_bank_generated_v0" / "problems.jsonl"


def build_distractor_codes(
    injection: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """L4 정본에서 객관식 주입 매핑을 조립 — 참조 무결성은 조성 루트가 소유(fail-fast).

    미등록 오개념 id·op-code, 또는 op-code가 다른 오개념을 가리키면 `KeyError`로 즉시 실패한다
    (조용한 무매핑 금지) — 배치가 잘못된 태깅을 코퍼스에 싣는 것을 원천 차단. `injection` 미지정 시
    quad 기본 매핑(`_MC_INJECTION`)을 검증한다(하위호환) — calc 극값 MC는 `_CALC_MC_INJECTION` 주입.
    """
    inj = injection if injection is not None else _MC_INJECTION
    for op_key, (misconception_id, op_code) in inj.items():
        if misconception_id not in CATALOG_BY_ID:
            raise KeyError(
                f"주입 오개념 id가 정본 카탈로그에 없음: {misconception_id!r} (op키 {op_key})"
            )
        op = DISTRACTOR_BY_ID.get(op_code)
        if op is None:
            raise KeyError(f"주입 op-code가 DISTRACTOR_CATALOG에 없음: {op_code!r} (op키 {op_key})")
        if op.misconception_id != misconception_id:
            raise KeyError(
                f"op-code {op_code!r}의 오개념({op.misconception_id!r})이 주입 오개념"
                f"({misconception_id!r})과 불일치 — 정본 정합 위반"
            )
    return dict(inj)


def _record_to_json(record: ProblemBankRecord) -> dict[str, Any]:
    """저장 레코드 → 코퍼스 JSONL dict — 기존 v0 직렬화 형태와 정확 일치(라운드트립 봉인).

    Problem 필드(mode="json"·None 제외) + 저작 메타(`_AUTHORING_KEYS`: license·generation_type·
    (original_source)·concepts·verify). `load_problem_bank_records`가 그대로 되읽는다.
    """
    data: dict[str, Any] = record.problem.model_dump(mode="json", exclude_none=True)
    data["license"] = record.provenance.license
    data["generation_type"] = record.provenance.generation_type
    if record.provenance.original_source is not None:
        data["original_source"] = record.provenance.original_source
    # 저작 서명(PB-15) — 기록이 있을 때만 키를 싣는다. 없는 레코드(결정론 생성기·구 코퍼스)는
    # 종전과 바이트 동일하다(키 집합 동결 테스트·기존 코퍼스 라운드트립 회귀 0).
    if record.provenance.authored_by is not None:
        data["authored_by"] = record.provenance.authored_by
    data["concepts"] = [
        {"concept_src_id": tag.concept_src_id, "role": tag.role, "relevance": tag.relevance}
        for tag in record.concept_tags
    ]
    # S4-14 — relations는 빈 리스트라도 균일하게 기록한다(필드 존재 자체가 "관계 계산이 이
    # 코퍼스에 배선돼 있다"는 신호 — 없는 키와 빈 리스트를 구분해야 하는 하류 테스트
    # `test_corpus_quality.py`의 키 집합 정합 봉인과도 정합).
    data["relations"] = [
        {
            "parent_slug": tag.parent_slug,
            "relation_type": tag.relation_type,
            "similarity_score": tag.similarity_score,
        }
        for tag in record.relations
    ]
    verify: dict[str, Any] = {
        "conditions": record.verify.conditions,
        "answer_map": dict(record.verify.answer_map),
    }
    if record.verify.solution_steps is not None:
        verify["solution_steps"] = list(record.verify.solution_steps)
    if record.verify.answer_selection is not None:
        verify["answer_selection"] = record.verify.answer_selection
    if record.verify.answer_aggregate is not None:
        verify["answer_aggregate"] = record.verify.answer_aggregate
    if record.verify.answer_kind is not None:
        verify["answer_kind"] = record.verify.answer_kind
    if record.verify.verification_tier is not None:
        verify["verification_tier"] = record.verify.verification_tier
    data["verify"] = verify
    return data


def _tagged_record(record: ProblemBankRecord) -> ProblemBankRecord:
    """sink 기록 직전 시그니처 태깅(S2-06) — 태거가 단일 권위(생성기는 빈 배열).

    `apply_signatures`는 유도 결과가 기존과 같으면 **원본 Problem 객체 그대로** 돌려주므로(멱등),
    규칙 미해당인 기존 문제군 레코드는 여기서도 원본 레코드 그대로다 — 직렬화 바이트 불변(비날조).
    """
    problem = apply_signatures(record.problem)
    if problem is record.problem:
        return record
    return replace(record, problem=problem)


# S4-14 스켈레톤 동일 밴드 "유사" 관계 — 전 쌍 연결은 밴드당 최대 ~17,000행(QUAD-EQ 443건
# 기준 C(443,2))이라 CLAUDE.md 관계 폭발 금지 위반. 정렬 후 인접 K건 백엣지만 잇는 선형 체인으로
# 상한을 건다(밴드당 관계 수 ≤ K × 밴드 크기 — 선형).
_SIMILAR_RELATION_TYPE = "유사"
_SIMILAR_SCORE = 0.6
_SIMILAR_BACK_EDGES = 3


def _attach_similar_relations(
    records: Sequence[ProblemBankRecord], *, k: int = _SIMILAR_BACK_EDGES
) -> list[ProblemBankRecord]:
    """스켈레톤 동일 밴드(문제군) 레코드에 "유사" 관계를 선형 체인으로 부여(anti-explosion).

    그룹핑 키 `(unit_codes, question_format, answer_format)` — 같은 문제군·형식의 문제만
    "유사" 후보. 그룹 내 `(difficulty_overall or 0.0, slug)` 정렬 후 인덱스 i(≥1)마다 직전
    K건(`range(max(0, i-k), i)`)만 후방 "유사" 관계로 잇는다(전 쌍 연결 금지 — 그룹 크기 N이면
    관계 O(N)만 생성, O(N²) 아님). 입력 리스트 순서는 보존한다(정렬은 관계 계산 내부 상태일 뿐 —
    반환은 원 인덱스 순).
    """
    groups: dict[tuple[Any, ...], list[tuple[int, ProblemBankRecord]]] = defaultdict(list)
    for idx, record in enumerate(records):
        key = (
            tuple(record.problem.unit_codes),
            record.problem.question_format,
            record.problem.answer_format,
        )
        groups[key].append((idx, record))

    new_tags_by_index: dict[int, tuple[ProblemRelationTag, ...]] = {}
    for members in groups.values():
        ordered = sorted(
            members, key=lambda pair: (pair[1].problem.difficulty_overall or 0.0, pair[1].slug)
        )
        for pos in range(1, len(ordered)):
            idx, record = ordered[pos]
            back_edges = tuple(
                ProblemRelationTag(
                    parent_slug=ordered[j][1].slug,
                    relation_type=_SIMILAR_RELATION_TYPE,
                    similarity_score=_SIMILAR_SCORE,
                )
                for j in range(max(0, pos - k), pos)
            )
            new_tags_by_index[idx] = record.relations + back_edges

    return [
        replace(record, relations=new_tags_by_index.get(idx, record.relations))
        for idx, record in enumerate(records)
    ]


class JsonlCorpusSink:
    """JSONL 저장 좌석 — `ProblemBankSink` 구조 충족(populate만)·메모리 수집 후 `write`로 기록.

    오케스트레이터는 후보 1건을 단일 레코드 배치로 넘긴다(S2-b seam 재사용) — 이 sink는 DB 대신
    메모리에 쌓았다가 배치 종료 후 한 번에 파일로 쓴다(부분 기록 없음·원자성).
    """

    def __init__(self) -> None:
        self._records: list[ProblemBankRecord] = []

    @property
    def records(self) -> list[ProblemBankRecord]:
        return list(self._records)

    def set_records(self, records: list[ProblemBankRecord]) -> None:
        """전 밴드 수집 후 후처리(S4-14 관계 부여 등) 반영 — 원소 교체(개수 불변 전제)."""
        self._records = records

    def populate(self, records: list[ProblemBankRecord]) -> ProblemBankPopulateReport:
        """레코드 배치를 메모리에 적재 — DB store와 동일 좌석 계약(리포트 반환)."""
        self._records.extend(records)
        return ProblemBankPopulateReport(
            problems_loaded=len(records),
            problem_concepts_loaded=sum(len(r.concept_tags) for r in records),
            concepts_skipped=0,
        )

    def write(self, path: Path) -> int:
        """수집분 전체를 JSONL로 기록(기존 파일 전면 교체) — 기록 행 수 반환.

        기록 직전 전 레코드에 시그니처 태거를 적용한다(`_tagged_record`·S2-06) — 규칙 미해당
        레코드는 원본 그대로라 기존 문제군의 바이트가 불변이다.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(_record_to_json(_tagged_record(r)), ensure_ascii=False)
            for r in self._records
        ]
        path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
        return len(lines)


@dataclass(frozen=True, slots=True)
class BandResult:
    """밴드 1개 실행 결과 — 요청/저장 수 + 미저장 사유(조용한 실패 금지)."""

    name: str
    requested: int
    stored: int
    failure_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CorpusBatchReport:
    """배치 전체 리포트 — 밴드별 결과·총 저장 수·기록 행 수(dry-run이면 None).

    `review_outcomes`는 전 밴드에서 *비수용*(수용/적재 안 됨)으로 판정된 GenerationOutcome을
    누적한 것 — needs_review 후보의 사람 검수·거부 후보 진단·임계값 보정 입력(휘발 방지·후보+근거
    보존). `to_json`엔 카운트만 싣는다(outcome 객체는 워크리스트 렌더 전용).
    """

    bands: list[BandResult]
    total_requested: int
    total_stored: int
    written: int | None
    out_path: str
    review_outcomes: list[GenerationOutcome] = field(default_factory=list)

    @property
    def fulfilled(self) -> bool:
        """수율 충족 — 요청 전량이 게이트를 통과해 저장됐는가."""
        return self.total_stored == self.total_requested

    def to_json(self) -> dict[str, Any]:
        return {
            "bands": [
                {
                    "name": b.name,
                    "requested": b.requested,
                    "stored": b.stored,
                    "failure_reasons": b.failure_reasons,
                }
                for b in self.bands
            ],
            "total_requested": self.total_requested,
            "total_stored": self.total_stored,
            "written": self.written,
            "out_path": self.out_path,
            "fulfilled": self.fulfilled,
            "review_outcomes_count": len(self.review_outcomes),
        }


def run_corpus_batch(
    *,
    out_path: Path | None = None,
    short_n: int = _DEFAULT_SHORT_N,
    mc_n: int = _DEFAULT_MC_N,
    sqrt_n: int = _DEFAULT_SQRT_N,
    sqrt_mc_n: int = _DEFAULT_SQRT_MC_N,
    calc_extremum_n: int = _DEFAULT_CALC_EXTREMUM_N,
    calc_tangent_n: int = _DEFAULT_CALC_TANGENT_N,
    calc_value_n: int = _DEFAULT_CALC_VALUE_N,
    calc_value_mc_n: int = _DEFAULT_CALC_VALUE_MC_N,
    calc_extremum_irr_n: int = _DEFAULT_CALC_EXTREMUM_IRR_N,
    exp_n: int = _DEFAULT_EXP_N,
    log_n: int = _DEFAULT_LOG_N,
    arith_n: int = _DEFAULT_ARITH_N,
    geo_n: int = _DEFAULT_GEO_N,
    trig_n: int = _DEFAULT_TRIG_N,
    arith_sum_n: int = _DEFAULT_ARITH_SUM_N,
    geo_sum_n: int = _DEFAULT_GEO_SUM_N,
    trig_eq_n: int = _DEFAULT_TRIG_EQ_N,
    seq_inductive_n: int = _DEFAULT_SEQ_INDUCTIVE_N,
    write: bool = True,
) -> CorpusBatchReport:
    """밴드 배치 실행 — 문제군별 signature_index·밴드별 스펙 정합·JSONL 기록(순수 결정론).

    밴드 스펙의 `target_misconception_ids`는 그 밴드 후보가 실제로 방출하는 오개념 집합과
    일치시킨다(mc·sqrt_mc=주입 2종·나머지=∅) — 게이트 오개념 Jaccard가 항상 1.0(빈 spec에
    오개념 도입 시 0.0인 규칙과 정합). quad 4밴드 난이도는 2.5·calc 밴드는 3.3 고정(gap ≤ 안전폭).

    문제군별 signature_index 분리: quad 4밴드(이차방정식 근)는 **공유** index(형식 파티션이 겹침
    차단), calc 밴드(삼차 극값)는 **별도** index다 — calc conditions는 도함수 방정식이라 이차방정식
    과 구조 동형이라, 공유 시 거짓 cross-군 dedup이 난다. 두 군은 sink에 순차 append(quad→calc).
    """
    resolved_out = out_path if out_path is not None else _default_out_path()
    codes = build_distractor_codes()
    mc_target_ids = frozenset(misconception_id for misconception_id, _ in codes.values())
    mc_variants: frozenset[str] = frozenset({"multiple_choice", "sqrt_multiple_choice"})

    # 비수용 outcome 포착(휘발 방지) — 밴드 블록을 *건드리지 않고* orchestrator `run_batch`를
    # 얇은 로컬 래퍼로 감싼다. 아래 모든 밴드의 `run_batch(...)` 호출이 이름해석상 이 래퍼로
    # 잡혀(모듈 import는 `_orchestrator_run_batch`), 수용 외 outcome만 `review_outcomes`에 쌓는다.
    # 반환·수율·리포트는 원본 그대로(side-effect는 누적뿐·결정론/바이트 동일 불변).
    review_outcomes: list[GenerationOutcome] = []

    def run_batch(
        spec: EquivalenceSpec,
        generator: EquivalentProblemGenerator,
        n: int,
        *,
        signature_index: MutableSet[str],
        store: ProblemBankSink,
    ) -> list[GenerationOutcome]:
        outcomes = _orchestrator_run_batch(
            spec, generator, n, signature_index=signature_index, store=store
        )
        review_outcomes.extend(
            o for o in outcomes if o.status not in ("accepted_stored", "accepted")
        )
        return outcomes

    sink = JsonlCorpusSink()
    signature_index: set[str] = set()
    band_plans: list[tuple[str, GeneratorVariant, int, frozenset[str]]] = [
        ("short", "short_answer", short_n, frozenset()),
        ("mc", "multiple_choice", mc_n, mc_target_ids),
        ("sqrt", "sqrt", sqrt_n, frozenset()),
        ("sqrt_mc", "sqrt_multiple_choice", sqrt_mc_n, mc_target_ids),
    ]

    bands: list[BandResult] = []
    for name, variant, n, target_ids in band_plans:
        spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_STANDARD_CODE}),
            target_misconception_ids=target_ids,
            difficulty_overall=_SPEC_DIFFICULTY,
            answer_format=None,
        )
        generator = SkeletonEquivalentProblemGenerator(
            variant=variant,
            distractor_codes=codes if variant in mc_variants else None,
            skip_signatures=signature_index,
        )
        outcomes = run_batch(spec, generator, n, signature_index=signature_index, store=sink)
        stored = sum(1 for o in outcomes if o.status == "accepted_stored")
        failure_reasons = [
            reason
            for outcome in outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(name=name, requested=n, stored=stored, failure_reasons=failure_reasons)
        )

    # ── calc 문제군(삼차 극값) — 별도 signature_index(도함수 방정식 cross-군 오dedup 방지) ──
    if calc_extremum_n > 0:
        calc_index: set[str] = set()
        calc_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_CALC_STANDARD_CODE}),
            target_misconception_ids=frozenset(),
            difficulty_overall=_CALC_SPEC_DIFFICULTY,
            answer_format=None,
        )
        calc_generator = CalculusExtremumSkeletonGenerator(skip_signatures=calc_index)
        calc_outcomes = run_batch(
            calc_spec, calc_generator, calc_extremum_n, signature_index=calc_index, store=sink
        )
        calc_stored = sum(1 for o in calc_outcomes if o.status == "accepted_stored")
        calc_failures = [
            reason
            for outcome in calc_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name="calc-extremum",
                requested=calc_extremum_n,
                stored=calc_stored,
                failure_reasons=calc_failures,
            )
        )

    # ── calc 문제군(삼차 접선 기울기) — 또 별도 signature_index(도함수 방정식 cross-군 방지) ──
    if calc_tangent_n > 0:
        tangent_index: set[str] = set()
        tangent_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_TANGENT_STANDARD_CODE}),
            target_misconception_ids=frozenset(),
            difficulty_overall=_TANGENT_SPEC_DIFFICULTY,
            answer_format=None,
        )
        tangent_generator = CalculusTangentSlopeSkeletonGenerator(skip_signatures=tangent_index)
        tangent_outcomes = run_batch(
            tangent_spec,
            tangent_generator,
            calc_tangent_n,
            signature_index=tangent_index,
            store=sink,
        )
        tangent_stored = sum(1 for o in tangent_outcomes if o.status == "accepted_stored")
        tangent_failures = [
            reason
            for outcome in tangent_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name="calc-tangent",
                requested=calc_tangent_n,
                stored=tangent_stored,
                failure_reasons=tangent_failures,
            )
        )

    # ── calc 문제군(삼차 극값의 값) — 또 별도 signature_index(극값 쌍 이차방정식 cross-군 방지) ──
    if calc_value_n > 0:
        value_index: set[str] = set()
        value_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_VALUE_STANDARD_CODE}),
            target_misconception_ids=frozenset(),
            difficulty_overall=_VALUE_SPEC_DIFFICULTY,
            answer_format=None,
        )
        value_generator = CalculusExtremumValueSkeletonGenerator(skip_signatures=value_index)
        value_outcomes = run_batch(
            value_spec, value_generator, calc_value_n, signature_index=value_index, store=sink
        )
        value_stored = sum(1 for o in value_outcomes if o.status == "accepted_stored")
        value_failures = [
            reason
            for outcome in value_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name="calc-value",
                requested=calc_value_n,
                stored=value_stored,
                failure_reasons=value_failures,
            )
        )

    # ── calc 문제군(삼차 극값의 값 객관식) — 또 별도 signature_index·오개념 distractor 2종 주입 ──
    if calc_value_mc_n > 0:
        value_mc_codes = build_distractor_codes(_CALC_MC_INJECTION)
        value_mc_target_ids = frozenset(mid for mid, _ in value_mc_codes.values())
        value_mc_index: set[str] = set()
        value_mc_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_VALUE_MC_STANDARD_CODE}),
            target_misconception_ids=value_mc_target_ids,
            difficulty_overall=_VALUE_MC_SPEC_DIFFICULTY,
            answer_format=None,
        )
        value_mc_generator = CalculusExtremumMCSkeletonGenerator(
            value_mc_codes, skip_signatures=value_mc_index
        )
        value_mc_outcomes = run_batch(
            value_mc_spec,
            value_mc_generator,
            calc_value_mc_n,
            signature_index=value_mc_index,
            store=sink,
        )
        value_mc_stored = sum(1 for o in value_mc_outcomes if o.status == "accepted_stored")
        value_mc_failures = [
            reason
            for outcome in value_mc_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name="calc-value-mc",
                requested=calc_value_mc_n,
                stored=value_mc_stored,
                failure_reasons=value_mc_failures,
            )
        )

    # ── calc 문제군(무리 임계점 극값) — 또 별도 signature_index. 도함수 monic이 판별식 비제곱이라
    #    정수 극값과 근의 체가 달라 signature가 애초 서로소지만 calc 규약대로 index 분리(이중 방어).
    #    답만 무리수(sqrt 정확값)·오개념 주입 0(단답형)이라 target_misconception_ids=∅. ──
    if calc_extremum_irr_n > 0:
        irr_index: set[str] = set()
        irr_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_IRR_STANDARD_CODE}),
            target_misconception_ids=frozenset(),
            difficulty_overall=_IRR_SPEC_DIFFICULTY,
            answer_format=None,
        )
        irr_generator = CalculusIrrationalExtremumSkeletonGenerator(skip_signatures=irr_index)
        irr_outcomes = run_batch(
            irr_spec, irr_generator, calc_extremum_irr_n, signature_index=irr_index, store=sink
        )
        irr_stored = sum(1 for o in irr_outcomes if o.status == "accepted_stored")
        irr_failures = [
            reason
            for outcome in irr_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name="calc-extremum-irr",
                requested=calc_extremum_irr_n,
                stored=irr_stored,
                failure_reasons=irr_failures,
            )
        )

    # ── 대수 문제군(지수·로그 방정식) — 비다항 conditions(signature=None)이라 별도 index지만
    #    실질 dedup 없음(풀 결정론 유일). quad/calc와 구조 signature가 애초에 안 겹친다. ──
    for band_name, gen_factory, count in (
        ("exp", ExponentialEquationSkeletonGenerator, exp_n),
        ("log", LogarithmicEquationSkeletonGenerator, log_n),
    ):
        if count <= 0:
            continue
        explog_index: set[str] = set()
        explog_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({_EXPLOG_STANDARD_CODE}),
            target_misconception_ids=frozenset(),
            difficulty_overall=_EXPLOG_SPEC_DIFFICULTY,
            answer_format=None,
        )
        explog_outcomes = run_batch(
            explog_spec,
            gen_factory(skip_signatures=explog_index),
            count,
            signature_index=explog_index,
            store=sink,
        )
        explog_stored = sum(1 for o in explog_outcomes if o.status == "accepted_stored")
        explog_failures = [
            reason
            for outcome in explog_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name=band_name,
                requested=count,
                stored=explog_stored,
                failure_reasons=explog_failures,
            )
        )

    # ── 수열·삼각 문제군 — 일반항·특수각값(다항 `x − 상수`·답 dedup)과 수열합(등차·등비합·다항
    #    답 dedup)·삼각방정식(초월함수·signature=None·slug 위임)을 함께 소비. 밴드마다 별도 index
    #    (문제군 분리·calc 패턴 미러) — 모두 `skip_signatures` 생성자 좌석을 공유(도메인 분담). ──
    for seq_name, seq_factory, seq_count, standard_code, difficulty in (
        (
            "arith",
            ArithmeticSequenceSkeletonGenerator,
            arith_n,
            _ARITH_STANDARD_CODE,
            _ARITH_SPEC_DIFFICULTY,
        ),
        (
            "geo",
            GeometricSequenceSkeletonGenerator,
            geo_n,
            _GEO_STANDARD_CODE,
            _GEO_SPEC_DIFFICULTY,
        ),
        (
            "trig",
            TrigonometricValueSkeletonGenerator,
            trig_n,
            _TRIG_STANDARD_CODE,
            _TRIG_SPEC_DIFFICULTY,
        ),
        (
            "arith-sum",
            ArithmeticSumSkeletonGenerator,
            arith_sum_n,
            _ARITH_SUM_STANDARD_CODE,
            _ARITH_SUM_SPEC_DIFFICULTY,
        ),
        (
            "geo-sum",
            GeometricSumSkeletonGenerator,
            geo_sum_n,
            _GEO_SUM_STANDARD_CODE,
            _GEO_SUM_SPEC_DIFFICULTY,
        ),
        (
            "trig-eq",
            TrigonometricEquationSkeletonGenerator,
            trig_eq_n,
            _TRIG_EQ_STANDARD_CODE,
            _TRIG_EQ_SPEC_DIFFICULTY,
        ),
        (
            # 귀납 정의 수열(S2-06) — (가)(나) 조건 나열 + 점화식 발문. 시그니처 태거의 실제
            # 양성 밴드. **마지막 밴드**로 append해 기존 코퍼스 590행 뒤에 붙는다(diff 최소).
            "seq-inductive",
            InductiveSequenceSkeletonGenerator,
            seq_inductive_n,
            _INDSEQ_STANDARD_CODE,
            _INDSEQ_SPEC_DIFFICULTY,
        ),
    ):
        if seq_count <= 0:
            continue
        seq_index: set[str] = set()
        seq_spec = EquivalenceSpec(
            achievement_standard_codes=frozenset({standard_code}),
            target_misconception_ids=frozenset(),
            difficulty_overall=difficulty,
            answer_format=None,
        )
        seq_outcomes = run_batch(
            seq_spec,
            seq_factory(skip_signatures=seq_index),
            seq_count,
            signature_index=seq_index,
            store=sink,
        )
        seq_stored = sum(1 for o in seq_outcomes if o.status == "accepted_stored")
        seq_failures = [
            reason
            for outcome in seq_outcomes
            if outcome.status != "accepted_stored"
            for reason in (outcome.reasons or [f"status={outcome.status}"])
        ]
        bands.append(
            BandResult(
                name=seq_name,
                requested=seq_count,
                stored=seq_stored,
                failure_reasons=seq_failures,
            )
        )

    total_requested = sum(b.requested for b in bands)
    total_stored = sum(b.stored for b in bands)
    # S4-14 — 전 밴드 누적 후 1회 유사 관계 부여(밴드별 개별 호출 아님 — 그룹핑이 문제군 전체
    # 기준이라 밴드 경계와 무관하게 같은 (unit_codes, question_format, answer_format)는 한 그룹).
    sink.set_records(_attach_similar_relations(sink.records))
    written = sink.write(resolved_out) if write else None
    return CorpusBatchReport(
        bands=bands,
        total_requested=total_requested,
        total_stored=total_stored,
        written=written,
        out_path=str(resolved_out),
        review_outcomes=review_outcomes,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 리포트를 JSON으로 stdout에 내고, 수율 미달이면 종료 코드 1."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_batch",
        description=(
            "동등문제 스켈레톤 코퍼스 배치(S2-p) — 4밴드(short/mc/sqrt/sqrt_mc)를 4종 게이트에 "
            "태워 JSONL 코퍼스를 결정론 재생성한다(LLM 0·DB 0)."
        ),
    )
    parser.add_argument("--out", type=Path, default=None, help="산출 JSONL 경로(기본 코퍼스 v0).")
    parser.add_argument("--short", type=int, default=_DEFAULT_SHORT_N, help="유리근 단답형 수.")
    parser.add_argument("--mc", type=int, default=_DEFAULT_MC_N, help="유리근 객관식 수.")
    parser.add_argument("--sqrt", type=int, default=_DEFAULT_SQRT_N, help="무리근 단답형 수.")
    parser.add_argument("--sqrt-mc", type=int, default=_DEFAULT_SQRT_MC_N, help="무리근 객관식 수.")
    parser.add_argument(
        "--calc-extremum",
        type=int,
        default=_DEFAULT_CALC_EXTREMUM_N,
        help="미적분 극값(삼차함수 극대·극소 x좌표) 단답형 수.",
    )
    parser.add_argument(
        "--calc-tangent",
        type=int,
        default=_DEFAULT_CALC_TANGENT_N,
        help="미적분 접선 기울기(삼차함수 접선 기울기 m인 점의 x좌표) 단답형 수.",
    )
    parser.add_argument(
        "--calc-value",
        type=int,
        default=_DEFAULT_CALC_VALUE_N,
        help="미적분 극값의 값(삼차함수 극댓값·극솟값) 단답형 수.",
    )
    parser.add_argument(
        "--calc-value-mc",
        type=int,
        default=_DEFAULT_CALC_VALUE_MC_N,
        help="미적분 극값의 값(삼차함수 극댓값·극솟값) 객관식 수(오개념 distractor 태깅).",
    )
    parser.add_argument(
        "--calc-extremum-irr",
        type=int,
        default=_DEFAULT_CALC_EXTREMUM_IRR_N,
        help="미적분 무리 임계점 극값(삼차함수 극대·극소 x좌표 p±√q) 단답형 수.",
    )
    parser.add_argument(
        "--exp", type=int, default=_DEFAULT_EXP_N, help="지수방정식(bˣ=bᵏ) 단답형 수."
    )
    parser.add_argument(
        "--log", type=int, default=_DEFAULT_LOG_N, help="로그방정식(log_b x=k) 단답형 수."
    )
    parser.add_argument(
        "--arith", type=int, default=_DEFAULT_ARITH_N, help="등차수열(제n항) 단답형 수."
    )
    parser.add_argument(
        "--geo", type=int, default=_DEFAULT_GEO_N, help="등비수열(제n항) 단답형 수."
    )
    parser.add_argument(
        "--trig", type=int, default=_DEFAULT_TRIG_N, help="삼각함수 특수각 값 단답형 수."
    )
    parser.add_argument(
        "--arith-sum",
        type=int,
        default=_DEFAULT_ARITH_SUM_N,
        help="등차수열의 합(Sₙ=n(2a+(n−1)d)/2) 단답형 수.",
    )
    parser.add_argument(
        "--geo-sum",
        type=int,
        default=_DEFAULT_GEO_SUM_N,
        help="등비수열의 합(Sₙ=a(rⁿ−1)/(r−1)·정수 합) 단답형 수.",
    )
    parser.add_argument(
        "--trig-eq",
        type=int,
        default=_DEFAULT_TRIG_EQ_N,
        help="삼각방정식(sin/cos x=v·0°≤x<360°·작은/큰 해) 단답형 수.",
    )
    parser.add_argument(
        "--seq-inductive",
        type=int,
        default=_DEFAULT_SEQ_INDUCTIVE_N,
        help="귀납 정의 수열((가)(나) 조건 나열+점화식·aₖ 값) 단답형 수 — 시그니처 양성 밴드.",
    )
    parser.add_argument("--dry-run", action="store_true", help="파일 미기록 — 수율·리포트만 확인.")
    parser.add_argument(
        "--worklist-out",
        type=Path,
        default=None,
        help="비수용 후보(검수필요·거부) 워크리스트 마크다운 경로(선택·미지정 시 미생성).",
    )
    args = parser.parse_args(argv)

    report = run_corpus_batch(
        out_path=args.out,
        short_n=args.short,
        mc_n=args.mc,
        sqrt_n=args.sqrt,
        sqrt_mc_n=args.sqrt_mc,
        calc_extremum_n=args.calc_extremum,
        calc_tangent_n=args.calc_tangent,
        calc_value_n=args.calc_value,
        calc_value_mc_n=args.calc_value_mc,
        calc_extremum_irr_n=args.calc_extremum_irr,
        exp_n=args.exp,
        log_n=args.log,
        arith_n=args.arith,
        geo_n=args.geo,
        trig_n=args.trig,
        arith_sum_n=args.arith_sum,
        geo_sum_n=args.geo_sum,
        trig_eq_n=args.trig_eq,
        seq_inductive_n=args.seq_inductive,
        write=not args.dry_run,
    )
    if args.worklist_out is not None:  # 비수용 후보 워크리스트 산출(선택·off by default)
        worklist_md = render_worklist_markdown(
            build_worklist(report.review_outcomes),
            total_outcomes=report.total_requested,
        )
        worklist_path = Path(args.worklist_out)
        worklist_path.write_text(worklist_md, encoding="utf-8")

    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report.fulfilled else 1


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
