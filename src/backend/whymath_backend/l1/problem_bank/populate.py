"""문제 코퍼스 → backend `problem`/`problem_concept` 적재 (S2-b·L1 자체생성 동등문제 경로).

MEMORY 2026-07-04 결정이 "문제 코퍼스→DB 적재 파이프라인 부재"로 S2에 미뤄둔 바로 그 경로다.
S2-a 수용 게이트(`l3/equivalent/acceptance.py`)를 *통과한* 자체생성 동등문제를 코퍼스 JSONL
(`data/corpus/problem_bank_v1/problems.jsonl`)에서 backend 영속 `problem`·`problem_concept`
테이블로 **멱등 upsert**한다. `l1/standards/populate`(성취기준)·`l1/atom_graph/populate`(원자
백본)의 *문제* 짝이며 같은 sync 좌석·멱등 규약·orphan skip 패턴을 따른다.

────────────────────────────────────────────────────────────────────────────
계층 경계 (import-linter 계약 — L1은 L3를 import하지 않는다)
────────────────────────────────────────────────────────────────────────────
이 적재기는 L1이므로 S2-a 게이트(`l3/equivalent/acceptance`·`l3/verify_*`)를 **부르지 않는다**
(L1→L3 import 금지·7계층 역방향 의존 금지). 코퍼스에 든 문제는 *저작 시점에 이미 S2-a 게이트를
통과한* 문제라는 **계약**으로 적재된다 — 게이트 통과 증명은 코퍼스 품질 테스트
(`tests/backend/l1/problem_bank/test_corpus_quality.py`·계층 밖이라 L1+L3 동시 import 허용)가
봉인한다. 적재 파이프라인은 코퍼스를 신뢰하되 *저작권 위생*(source_type/license)만 재확인한다.

────────────────────────────────────────────────────────────────────────────
코퍼스 포맷 (JSONL — 한 줄 = 문제 1개)
────────────────────────────────────────────────────────────────────────────
각 줄은 `schema.Problem` 필드 + *저작 메타*(Problem 스키마 밖 authoring 필드)를 함께 담는다.
Problem은 `extra="forbid"`라 authoring 필드를 남기면 검증에 거부되므로, 로더가 `_AUTHORING_KEYS`
(`concepts`·`verify`·`license`·`generation_type`·`original_source`)를 *분리*한 뒤 나머지를
`Problem.model_validate`에 넘긴다(본문 불변식은 Problem이 강제).
  - `concepts`: 개념 태깅 `[{concept_src_id, role, relevance}]` — populate가 크로스워크 해석
    (src→primary_atom_code→원자 행 concept_id·§원자 재연결)으로 `problem_concept` 적재(미해석
    개념은 orphan skip).
  - `verify`·`license`·`generation_type`·`original_source`: S2-a 게이트 재료(품질 테스트 소비).
    적재 파이프라인은 `license`(위생)만 보고 나머지 authoring은 레코드에 실어 반환만 한다.

────────────────────────────────────────────────────────────────────────────
저작권 위생 (코퍼스 신뢰의 최소 재확인 — 우선순위 #2)
────────────────────────────────────────────────────────────────────────────
학생에게 노출·저장되는 본문 레코드는 `source_type=자체생성`(WHYMATH_GENERATED)만 합법이다
(`schema/problem.py::_METADATA_ONLY_SOURCES` 규칙). 로더는 각 레코드가 ① `source_type==자체생성`
② `license==WHYMATH_GENERATED` ③ 안정 키 `slug` 보유인지 확인하고, 아니면 `ProblemCorpusError`로
*거부*한다(조용한 통과 금지). 본문 미보유 불변식(평가원/EBS/교과서 본문 금지)은 `Problem.
from_schema`가 거치는 `Problem` 검증이 이미 강제하므로 이 로더는 재구현하지 않는다.

────────────────────────────────────────────────────────────────────────────
멱등 (PG ON CONFLICT — standards/atom_graph 규약)
────────────────────────────────────────────────────────────────────────────
  - 문제: 안정 키 `slug`(UNIQUE) 충돌 시 `INSERT ... ON CONFLICT(slug) DO UPDATE`로 본문·메타를
    갱신하되 **problem_id(PK)·slug·created_at은 SET하지 않아 보존**한다(재적재가 식별자·생성시각
    불변). `problem_id`는 코퍼스에 없으면 매번 새로 생성되나 slug 충돌 시 기존 행의 problem_id가
    유지되며 `RETURNING problem_id`로 그 값을 받아 `problem_concept` FK에 쓴다(2회 적재 count 안정).
    입력 내 slug 중복은 *마지막 우선* dedup(단일 배치 ON CONFLICT 중복행 오류 방지·standards 선례).
  - 개념 태깅: `concept_src_id`를 **원자 백본 크로스워크 해석**(아래 §원자 재연결)으로 원자 행
    concept_id에 해석(해석 실패는 orphan skip·집계 보고)한 뒤, 복합 PK `(problem_id, concept_id,
    role)` 충돌 시 `DO UPDATE`로 `relevance`만 갱신한다. 해석된 `(concept_id, role)` 접힘 시
    `relevance`는 **max**(None은 최저 취급 — 조용한 마지막-우선 덮어쓰기 금지).
  - reconcile: 문제별 upsert 후 *같은 트랜잭션*에서 이번 해석 집합에 없는 기존 `problem_concept`
    행을 DELETE한다(해석 0건이면 그 문제의 연결 전체 삭제). upsert-only로는 재연결 시 구 437
    legacy 행이 잔류하므로 재실행이 곧 정합 회복이다.

────────────────────────────────────────────────────────────────────────────
원자 백본 재연결 (S2-03 — src 태그 → 크로스워크 primary → 원자 행 UUID)
────────────────────────────────────────────────────────────────────────────
코퍼스 태그 `concept_src_id`(구 437 src 공간·예 'HK06')는 과거 `{concept.source_id: concept_id}`
맵으로 해석돼 **구 437 legacy 행**(source_id 보유)에만 닿았다 — 소비처(mastery→weak enrich)는
concept_id가 *원자 행*(code=원자코드)을 가리켜야 `fetch_atom_node_meta`에 닿으므로, 해석 체인을
원자 축으로 전환한다:

  ① 파일 해석: crosswalk(`concept_atom_crosswalk_v1/crosswalk.jsonl`·concept_id 키)와 다리
     (`concept_graph_v1/graph.json`·concept_id→src_id)를 조인해 `{src_id: primary_atom_code}`
     (`derive_src_to_primary_atom` — src 중복 시 ValueError·조용히 덮지 않음)
  ② DB 단일 조회: `concept.code IN (원자 code들)`로 원자 행 UUID 확보
  ③ 합성: `{src_id: 원자 행 concept_id}` — 원자 행 미적재 src는 맵 제외(기존 orphan skip 경로).

**귀속 규칙**: 전 role이 `primary_atom_code` 1개에 귀속된다(SUPPORTING을 atom_codes 전체로 벌리지
않음) — ⓐ 크로스워크 데이터카드 §귀속: primary 귀속은 mastery/오개념 *이력 귀속* 계약이고 문제
태깅은 그 이력의 상류다 ⓑ 스킬 *전파*(atom_codes 전체)는 별도 축(`transfer.py`)으로 이미 존재
ⓒ 태깅 팽창은 관계 폭발(anti-explosion·CLAUDE.md 7대 붕괴 연쇄)의 초입이다.

**마이그레이션 판정 — 스키마 무변경**: FK 대상 `concept.concept_id`는 원자 행에도 동일 컬럼이다.
재연결의 정합 경로는 *populate 재실행 + reconcile*(구 437 잔재 자동 청소)이며 alembic head 불변
(`c4d5e6f0a1b2`·마이그레이션 파일 무추가).

sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0·standards/atom_graph와 동일 좌석).
자격은 env(`Settings.sync_database_url`)·하드코딩 0.

사용:
    python -m whymath_backend.l1.problem_bank.populate \\
        --problems data/corpus/problem_bank_v1/problems.jsonl

7계층: L1 데이터 기반의 *런타임 엔티티 적재*. 소비(게이팅·진단·출제)는 이 행을 *조회*하되 여기서
구현하지 않는다(역방향 의존 금지).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from whymath_backend.config import Settings, get_settings

# 크로스워크 해석 다리 재사용(S2-03·intra-L1 import — populate가 이미 l1 내부 import 선례 보유).
from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    CrosswalkRecord,
    load_concept_src_bridge,
    load_crosswalk_records,
)

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — standards/atom_graph와 동일 좌석. (intra-L1 import)
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.enums import ConceptRole, LicenseType, RelationType, SourceType
from whymath_backend.schema.problem import Problem

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# 코퍼스 기본 경로(신설 problem_bank_v1·손저작 시드).
_DEFAULT_PROBLEMS = Path("data/corpus/problem_bank_v1/problems.jsonl")
# 크로스워크 코퍼스 기본 경로(S2-03 원자 재연결 — _DEFAULT_PROBLEMS와 동일 repo-root 상대 규약).
_DEFAULT_CROSSWALK = Path("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl")
# 구 437 개념그래프(다리 concept_id→src_id) 기본 경로 — legacy_snapshot의 *빌드타임* 소비
# (`test_legacy_snapshot_governance.py` audit 화이트리스트 등재·런타임 read 아님).
_DEFAULT_CONCEPT_GRAPH = Path("data/corpus/concept_graph_v1/graph.json")

# Problem 스키마 밖 *저작 메타* 키 — Problem.model_validate 전에 분리한다(extra=forbid 대응).
_AUTHORING_KEYS: frozenset[str] = frozenset(
    {"concepts", "verify", "license", "generation_type", "original_source", "relations"}
)

# 본문 보유가 합법인 출처·라이선스(코퍼스 위생) — 자체생성 동등문제만 적재한다.
_ACCEPTED_SOURCE_VALUE: str = SourceType.자체생성.value
_ACCEPTED_LICENSE_VALUE: str = LicenseType.WHYMATH_GENERATED.value

# 유효 개념 역할 값 집합(ConceptRole) — 태깅 role 검증용.
_CONCEPT_ROLE_VALUES: frozenset[str] = frozenset(r.value for r in ConceptRole)

# 유효 관계 유형 값 집합(RelationType) — S4-18 계보 태깅 relation_type 검증용.
_RELATION_TYPE_VALUES: frozenset[str] = frozenset(r.value for r in RelationType)

# 유효 verification_tier 값(l3/verification_tier.VerificationTier와 값 동기 — L1은 L3를 임포트할
# 수 없어 문자열 상수로 이중 관리한다. 미지값은 조용히 버리지 않고 ProblemCorpusError로 거부한다
# (검증 등급은 안전 신호라 sibling authoring 필드보다 엄격하게 다룬다).
_VERIFICATION_TIER_VALUES: frozenset[str] = frozenset({"machine_exhaustive", "machine_sampled"})


class ProblemCorpusError(ValueError):
    """문제 코퍼스가 저작권 위생·안정 키 규약을 어겨 적재를 거부할 때(조용한 통과 금지).

    거부 사유: ① `source_type != 자체생성`(본문 보유 불법 출처) ② `license != WHYMATH_GENERATED`
    ③ 안정 키 `slug` 부재(멱등 불가) ④ 개념 역할이 `ConceptRole` 밖. 본문 미보유 불변식(평가원/
    EBS/교과서) 위반은 `Problem` 검증이 먼저 `ValidationError`로 던지므로 여기 오지 않는다.
    """


# ──────────────────────────────────────────────────────────────────────────
# 저작 메타 타입 (Problem 스키마 밖 authoring — 로더가 분리·반환)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ConceptTag:
    """개념 태깅 1건 — `concept_src_id`(개념그래프 src_id)·역할·관련도(problem_concept 재료)."""

    concept_src_id: str
    role: str  # ConceptRole 값(PRIMARY/SUPPORTING/IMPLICIT/TESTED)
    relevance: float | None = None


@dataclass(frozen=True, slots=True)
class ProblemRelationTag:
    """변형 계보 1건(S4-18) — 이 레코드가 `parent_slug` 문제의 파생임을 선언(problem_relation 재료).

    방향은 항상 parent→이 레코드다(Kiki 결정: identity_id/Canonical 분리 — problem_id는
    개체마다 불변, 이 relation은 개별 변환 이력만 기록). `relation_type`은 `RelationType`
    (변형/유사/선수/심화/대조) 값 중 하나여야 한다 — 이 값 하나만 검증하고 그 밖은 그대로 보존.
    """

    parent_slug: str
    relation_type: str
    similarity_score: float | None = None


@dataclass(frozen=True, slots=True)
class ProblemVerifyMeta:
    """S2-a 정확성 게이트 재료 — 원 조건·치환맵·(선택)풀이 단계·근 선택. 적재엔 미사용(품질 테스트).

    `answer_selection`(S2-i·largest/smallest/unique): "큰 근/작은 근" 문제는 방정식만으론 답이
    유일하지 않아 게이트가 *어느 근인가*를 검증하는 데 쓴다(None=선택 요구 없음).
    """

    conditions: str | list[str]
    answer_map: dict[str, str]
    solution_steps: list[str] | None = None
    answer_selection: str | None = None
    answer_aggregate: str | None = None
    """S2 킬러 — 근 집계 검증 종류(sum/product). 답이 근이 아니라 근들의 합/곱인 킬러 문항."""
    answer_kind: str | None = None
    """개념형 — 개수/판정 검증 종류(개수·일대일·수렴·극한=함숫값·미분가능). 답이 값이 아닌 문항."""
    verification_tier: str | None = None
    """S4-13 유한표본 배치 — 기계 검증 강도(machine_exhaustive/machine_sampled). 부재=미각인
    구코퍼스."""


@dataclass(frozen=True, slots=True)
class ProblemProvenanceMeta:
    """S2-a 저작권 게이트 재료 — ContentProvenance(generation_type/license/original_source)."""

    generation_type: str
    license: str
    original_source: str | None = None


@dataclass(frozen=True, slots=True)
class ProblemBankRecord:
    """코퍼스 1레코드 = 검증된 Problem + 저작 메타(개념 태깅·verify·provenance·계보).

    적재 파이프라인은 `slug`·`problem`·`concept_tags`·`relations`만 소비한다. `verify`·
    `provenance`는 코퍼스 품질 테스트(S2-a 게이트 재현)가 쓰는 authoring이며 적재엔
    관여하지 않는다(계층 경계). `relations`는 기본값 `()`라 기존 생성자 호출부 전부 무영향.
    """

    slug: str
    problem: Problem
    concept_tags: tuple[ConceptTag, ...]
    verify: ProblemVerifyMeta
    provenance: ProblemProvenanceMeta
    relations: tuple[ProblemRelationTag, ...] = ()


@dataclass(frozen=True, slots=True)
class ProblemBankPopulateReport:
    """문제 코퍼스 적재 결과 요약(운영 가시성·테스트 단언용).

    `problems_loaded`(문제 upsert 행 수·dedup 후)·`problem_concepts_loaded`(개념 태깅 upsert 수)·
    `concepts_skipped`(미해석 개념 orphan skip 수)·`skipped_messages`(orphan 상세·조용한 누락 금지)·
    `problem_concepts_reconciled`(reconcile DELETE 행 수 — 구 연결 청소·기존 위치 인자 호환을 위해
    말미 기본값 필드로 추가)·`problem_relations_loaded`/`problem_relations_skipped`(S4-18 계보
    upsert 수·parent_slug 미해석 orphan skip 수 — 역시 말미 기본값 필드로 위치 인자 호환 유지).
    """

    problems_loaded: int
    problem_concepts_loaded: int
    concepts_skipped: int
    skipped_messages: list[str] = field(default_factory=list)
    problem_concepts_reconciled: int = 0
    problem_relations_loaded: int = 0
    problem_relations_skipped: int = 0


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 파싱 (JSONL → 검증된 ProblemBankRecord — authoring 분리·저작권 위생)
# ──────────────────────────────────────────────────────────────────────────
def _concept_tag_from_dict(raw: dict[str, Any], *, slug: str) -> ConceptTag:
    """개념 태깅 dict → `ConceptTag`(role 값 검증). 필수 키·역할 밖이면 `ProblemCorpusError`."""
    src_id = raw.get("concept_src_id")
    role = raw.get("role")
    if not isinstance(src_id, str) or not src_id:
        raise ProblemCorpusError(f"개념 태깅 concept_src_id 누락/형식오류: slug={slug} raw={raw!r}")
    if not isinstance(role, str) or role not in _CONCEPT_ROLE_VALUES:
        raise ProblemCorpusError(
            f"개념 태깅 role이 ConceptRole 밖: slug={slug} role={role!r} "
            f"(허용 {sorted(_CONCEPT_ROLE_VALUES)})"
        )
    relevance = raw.get("relevance")
    rel_value = float(relevance) if isinstance(relevance, (int, float)) else None
    return ConceptTag(concept_src_id=src_id, role=role, relevance=rel_value)


def _relation_tag_from_dict(raw: dict[str, Any], *, slug: str) -> ProblemRelationTag:
    """계보 태깅 dict → `ProblemRelationTag`(relation_type 값 검증). 필수 키·유형 밖이면 거부."""
    parent_slug = raw.get("parent_slug")
    relation_type = raw.get("relation_type")
    if not isinstance(parent_slug, str) or not parent_slug:
        raise ProblemCorpusError(f"계보 태깅 parent_slug 누락/형식오류: slug={slug} raw={raw!r}")
    if not isinstance(relation_type, str) or relation_type not in _RELATION_TYPE_VALUES:
        raise ProblemCorpusError(
            f"계보 태깅 relation_type이 RelationType 밖: slug={slug} "
            f"relation_type={relation_type!r} (허용 {sorted(_RELATION_TYPE_VALUES)})"
        )
    score = raw.get("similarity_score")
    score_value = float(score) if isinstance(score, (int, float)) else None
    return ProblemRelationTag(
        parent_slug=parent_slug, relation_type=relation_type, similarity_score=score_value
    )


def _record_from_line(raw: dict[str, Any]) -> ProblemBankRecord:
    """코퍼스 JSONL 한 줄(dict) → 검증된 `ProblemBankRecord`(authoring 분리·위생·Problem 검증).

    ① authoring 키(`_AUTHORING_KEYS`)를 분리 → ② 저작권 위생 확인(source_type=자체생성·license=
    WHYMATH_GENERATED·slug 보유) → ③ 나머지를 `Problem.model_validate`(본문 불변식 자동 강제) →
    ④ 개념 태깅·verify·provenance·계보(relations) 저작 메타 조립. 위생 위반은 `ProblemCorpusError`
    (조용한 통과 X).
    """
    data = dict(raw)  # 원본 불변(호출자 dict 보호)

    # ── ① authoring 분리 ──
    concepts_raw = data.pop("concepts", []) or []
    verify_raw = data.pop("verify", None)
    license_value = data.pop("license", None)
    generation_type = data.pop("generation_type", None)
    original_source = data.pop("original_source", None)
    relations_raw = data.pop("relations", []) or []

    # ── ② 저작권 위생(코퍼스 신뢰의 최소 재확인) ──
    slug = data.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ProblemCorpusError(f"안정 키 slug 부재 — 멱등 불가: raw={raw!r}")
    source_value = data.get("source_type")
    if source_value != _ACCEPTED_SOURCE_VALUE:
        raise ProblemCorpusError(
            f"코퍼스 위생 위반: source_type={source_value!r}는 적재 불가 — 본문 보유 문제는 "
            f"source_type={_ACCEPTED_SOURCE_VALUE!r}만 합법이다(평가원/EBS/교과서 등 메타 전용 "
            f"출처 거부·저작권 가이드 v2.0). slug={slug}"
        )
    if license_value != _ACCEPTED_LICENSE_VALUE:
        raise ProblemCorpusError(
            f"코퍼스 위생 위반: license={license_value!r}는 적재 불가 — 자체생성 본문의 지배 "
            f"license는 {_ACCEPTED_LICENSE_VALUE!r}여야 한다. slug={slug}"
        )

    # ── ③ Problem 검증(본문 불변식은 Problem이 강제 — 재구현 0) ──
    problem = Problem.model_validate(data)

    # ── ④ 저작 메타 조립 ──
    concept_tags = tuple(
        _concept_tag_from_dict(c, slug=slug) for c in concepts_raw if isinstance(c, dict)
    )
    relations = tuple(
        _relation_tag_from_dict(r, slug=slug) for r in relations_raw if isinstance(r, dict)
    )
    verify_meta = _verify_meta_from_raw(verify_raw, slug=slug)
    provenance_meta = ProblemProvenanceMeta(
        generation_type=str(generation_type) if generation_type is not None else "",
        license=str(license_value),
        original_source=str(original_source) if original_source is not None else None,
    )
    return ProblemBankRecord(
        slug=slug,
        problem=problem,
        concept_tags=concept_tags,
        verify=verify_meta,
        provenance=provenance_meta,
        relations=relations,
    )


def _verify_meta_from_raw(verify_raw: Any, *, slug: str) -> ProblemVerifyMeta:
    """verify authoring dict → `ProblemVerifyMeta`. 부재 시 빈 조건(품질 테스트가 unverifiable).

    미지 값 정책은 필드마다 다르며, **그 차이는 의도적이다**(EOS-85):

    - `answer_kind` — **통과**(불투명 문자열). 이 필드의 어휘는 *과목이 정하는 것*이라 CORE인
      적재기가 열거할 수 없다. 검증 가능 여부는 L3 검산이 판정한다.
    - `verification_tier` — **거부**(`ProblemCorpusError`). 이쪽은 *기계 검증 강도*를 뜻하는
      **플랫폼 어휘**라 과목과 무관하게 폐쇄집합이며, 오타가 조용히 통과하면 검증 강도를
      잘못 보고하게 된다.
    - `answer_selection`·`answer_aggregate` — **통과**(EOS-01). `answer_kind`와 같은 과목
      어휘이며 판정 권위도 같은 자리(L3 `verify_root_selection`·`verify_root_aggregate`)에 있다.

    ⚠ **기계 가드의 범위(있는 척 금지 · EOS-01 ② 실측)**: 이 세 필드의 어휘 열거는 두 정적
    축 중 **어느 쪽도 잡지 못한다**. ⑴ 경계 프로브(`eos_core_boundary_probe`)는 리터럴을
    `MATH_TYPE_RX` 접두 목록으로 판정하는데 `largest`·`smallest`·`unique`·`sum`·`product`는
    전부 미매치다(실측). 이 낱말들을 정규식에 넣으면 일반어라 거짓 양성이 신호를 덮는다 —
    그 판단은 프로브 자신의 주석이 이미 밝힌 설계다. ⑵ 불투명 페이로드 게이트는
    `ProblemStatement` DTO 필드를 축으로 삼는데 이 두 필드는 **DTO에 없다**(계약은 `answer`·
    `answer_kind`·`conditions` 3종만 불투명으로 선언). 즉 사각은 잘못 설정된 것이 아니라
    **설계상 범위 밖**이다. 그래서 이 축의 실질 보호는 아래 회귀 테스트(행동 축)가 맡는다 —
    `tests/backend/l1/problem_bank/test_populate.py`의 미등록 값 통과 단언 3종.
    (두 필드를 Subject Contract 필수층 DTO에 편입할지는 별건이다 — 필수층 추가는 "모든 과목이
    반드시 제공한다"는 선언이라 되돌리기 어렵고, `subject_adapter.py`가 그 게이트를 따로 둔다.)

    즉 판정 기준은 "폐쇄집합인가"가 아니라 **"누구의 어휘인가"**다 — 과목 어휘는 통과시키고
    플랫폼 어휘는 거부한다.
    """
    if not isinstance(verify_raw, dict):
        return ProblemVerifyMeta(conditions="", answer_map={})
    conditions = verify_raw.get("conditions", "")
    answer_map_raw = verify_raw.get("answer_map", {})
    steps_raw = verify_raw.get("solution_steps")
    if not isinstance(conditions, (str, list)):
        raise ProblemCorpusError(f"verify.conditions 형식오류: slug={slug} value={conditions!r}")
    answer_map = {str(k): str(v) for k, v in dict(answer_map_raw).items()}
    steps = [str(s) for s in steps_raw] if isinstance(steps_raw, list) else None
    # EOS-01 — `answer_selection`·`answer_aggregate`도 **불투명 문자열로 통과**시킨다.
    # EOS-85가 `answer_kind`에 세운 기준("폐쇄집합인가"가 아니라 "누구의 어휘인가")을 같은
    # 함수의 남은 두 형제에 적용한다. 실측(2026-09-07)으로 둘 다 **과목 어휘**임을 확인했다:
    #   · 판정 권위가 L3에 있다 — `l3/verify_answer.verify_root_selection`이
    #     `selection not in ("largest","smallest","unique")`이면 보수적으로 `None`을 낸다
    #     (`_CONCEPTUAL_VERIFIERS` 디스패치와 같은 구조). 적재기가 거를 일이 아니다.
    #   · 의미가 수학에 묶여 있다 — "근 중 가장 큰 값"·"근들의 합/곱"이며, 다른 과목은 같은
    #     자리에 다른 어휘를 담는다.
    # 종전엔 목록 밖 값이 예외도 경고도 없이 `None`이 됐다(answer_kind와 같은 조용한 손실).
    sel_raw = verify_raw.get("answer_selection")
    selection = sel_raw if isinstance(sel_raw, str) and sel_raw else None
    agg_raw = verify_raw.get("answer_aggregate")
    aggregate = agg_raw if isinstance(agg_raw, str) and agg_raw else None
    # EOS-85 — `answer_kind`는 **불투명 문자열로 그대로 통과**시킨다(어휘 열거 없음).
    # 종전엔 17종을 튜플로 열거하고 그 밖은 `None`으로 떨어뜨렸다. 두 가지가 문제였다:
    #   ⑴ **경계 위반** — 적재기는 CORE인데 수학 answer_kind 어휘를 알고 있었다. 경계 프로브
    #      (`eos_core_boundary_probe`)가 세던 리터럴 비교 **1건이 정확히 이 자리**였다.
    #   ⑵ **조용한 손실** — 목록에 없는 값이 예외도 경고도 없이 `None`이 됐다. 새 검증 종류를
    #      L3에 추가하고 여기를 안 고치면 그 문항의 검증 종류가 적재 시 사라지고, 화면에는
    #      "answer_kind 없는 문항"으로 보인다(S4-17 `finite_probability` 손실이 그 전례다).
    # 여기서는 **형식만** 본다(문자열인가·빈 값이 아닌가). *어떤 값이 검증 가능한가*의 판정은
    # L3 검산이 한다 — `l3.equivalent.acceptance._CONCEPTUAL_VERIFIERS`에 디스패치가 없으면
    # 그 문항은 개념형 검증을 건너뛴다. 즉 미지 값은 여기서 지워지는 대신 L3까지 도달해
    # **어디서 왜 못 쟀는지가 보이는** 형태가 된다.
    kind_raw = verify_raw.get("answer_kind")
    kind = kind_raw if isinstance(kind_raw, str) and kind_raw else None
    tier_raw = verify_raw.get("verification_tier")
    if tier_raw is not None and tier_raw not in _VERIFICATION_TIER_VALUES:
        raise ProblemCorpusError(
            f"verify.verification_tier가 알려진 값 밖: slug={slug} value={tier_raw!r} "
            f"(허용 {sorted(_VERIFICATION_TIER_VALUES)} 또는 None)"
        )
    return ProblemVerifyMeta(
        conditions=conditions,
        answer_map=answer_map,
        solution_steps=steps,
        answer_selection=selection,
        answer_aggregate=aggregate,
        answer_kind=kind,
        verification_tier=tier_raw,
    )


def load_problem_bank_records(problems_path: Path) -> list[ProblemBankRecord]:
    """문제 코퍼스 JSONL을 검증된 `ProblemBankRecord` 목록으로 로드(authoring 분리·위생·검증).

    빈 줄은 건너뛴다(관대). 각 줄은 `_record_from_line`이 authoring 분리·저작권 위생·Problem 검증을
    거친다 — 위생 위반은 `ProblemCorpusError`로 전파(조용한 통과 금지). 코퍼스 품질 테스트가 반환
    레코드의 `verify`/`provenance`로 S2-a 게이트를 재현한다.

    Raises:
        FileNotFoundError: problems_path 파일 부재.
        ProblemCorpusError: 저작권 위생·안정 키·역할 위반.
        pydantic.ValidationError: 레코드가 Problem 스키마·본문 불변식 위반.
    """
    text = problems_path.read_text(encoding="utf-8")
    records: list[ProblemBankRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        records.append(_record_from_line(json.loads(stripped)))
    return records


# ──────────────────────────────────────────────────────────────────────────
# 원자 백본 해석 (S2-03 — src 태그 → 크로스워크 primary_atom_code 순수 유도)
# ──────────────────────────────────────────────────────────────────────────
def derive_src_to_primary_atom(
    crosswalk: list[CrosswalkRecord],
    concept_src_bridge: Mapping[str, str],
) -> dict[str, str]:
    """크로스워크 × 다리 조인 → `{src_id: primary_atom_code}` 유도(순수·파일만·DB 무접촉).

    다리(`concept_id`→`src_id`)를 크로스워크 행 순회로 역전한다 — 한 src에 두 크로스워크 행이
    닿으면(역전 충돌) `ValueError`로 즉시 실패한다(조용히 덮지 않음·transfer.py 계약 §4 동형).
    `primary_atom_code`가 None(unmapped)인 행은 skip한다(강제 귀속 금지). 다리에 없는 크로스워크
    concept_id는 조인 실패로 즉시 오류다(`derive_atom_behavior_skills` 동형).

    Raises:
        ValueError: 다리 조인 실패(concept_id 부재) 또는 src 역전 충돌(중복).
    """
    out: dict[str, str] = {}
    for record in crosswalk:
        if record.primary_atom_code is None:  # unmapped — 강제 귀속 금지(skip)
            continue
        src_id = concept_src_bridge.get(record.concept_id)
        if src_id is None:
            raise ValueError(f"크로스워크 concept_id가 graph.json에 없음: {record.concept_id!r}")
        if src_id in out:
            raise ValueError(
                f"src_id {src_id!r}에 크로스워크 행이 중복으로 닿음(역전 충돌) — "
                f"조용히 덮지 않고 실패한다"
            )
        out[src_id] = record.primary_atom_code
    return out


# ──────────────────────────────────────────────────────────────────────────
# 적재기 (ProblemBankStore — slug ON CONFLICT·concept 해석·orphan skip·sync)
# ──────────────────────────────────────────────────────────────────────────
class ProblemBankStore:
    """문제 코퍼스 → backend `problem`/`problem_concept` 적재기 — slug 충돌 멱등 upsert(sync).

    `AchievementStandardStore`(성취기준)·`AtomBackendEdgeStore`(엣지)의 *문제* 짝이다(같은 sync
    좌석·멱등 규약·orphan skip). `populate`는 ① 크로스워크 해석 맵(`{src_id: 원자 행 concept_id}`
    — 모듈 docstring §원자 재연결)을 파일 해석 + DB 단일 조회로 만들고(N+1 0) ② 각 문제를
    `ON CONFLICT(slug) DO UPDATE ... RETURNING problem_id`로 멱등 적재해 안정 problem_id를 받은 뒤
    ③ 개념 태깅을 concept_id로 해석(orphan skip)해 `problem_concept`에 복합 PK 충돌 멱등 upsert하고
    ④ 같은 트랜잭션에서 해석 집합 밖 구 연결을 reconcile DELETE한다. sync 엔진은 슬3
    `_build_sync_engine`을 재사용해 지연 생성·캐시(seam 0).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
        crosswalk_path: Path = _DEFAULT_CROSSWALK,
        concept_graph_path: Path = _DEFAULT_CONCEPT_GRAPH,
    ) -> None:
        self._engine = engine
        self._settings = settings
        # 원자 재연결 해석 코퍼스 경로(S2-03) — 기본은 repo-root 상대 규약(_DEFAULT_* 상수).
        self._crosswalk_path = crosswalk_path
        self._concept_graph_path = concept_graph_path

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(standards 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def _load_source_id_to_concept_id(self) -> dict[str, Any]:
        """크로스워크 해석 + DB 단일 조회로 `{src_id: 원자 행 concept_id}` 맵 구축(N+1 0).

        S2-03 원자 재연결(모듈 docstring §원자 재연결): 구 `{concept.source_id: concept_id}` 전량
        조회는 원자 행(source_id NULL)에 닿지 못해 구 437 legacy 행만 가리켰다. 이제 ① 파일 해석
        (`derive_src_to_primary_atom` — crosswalk × 다리)으로 `{src_id: primary_atom_code}`를 만들고
        ② `concept.code IN (원자 code들)` 단일 조회로 원자 행 UUID를 받아 ③ `{src_id: concept_id}`
        로 합성한다(메서드명·반환형은 유지 — 호출부 diff 최소). 원자 행 미적재 src는 맵에서 빠져
        기존 orphan skip 보고 경로를 그대로 탄다(`l1/atom_graph` populate 선행 필요). 크로스워크·
        다리 파일 부재는 FileNotFoundError 전파(조용한 빈 맵 금지).
        """
        from sqlalchemy import select

        from whymath_backend.db.models.concept import Concept

        # ① 파일 해석 — {src_id: primary_atom_code}(순수·크로스워크 × 다리).
        src_to_atom = derive_src_to_primary_atom(
            load_crosswalk_records(self._crosswalk_path),
            load_concept_src_bridge(self._concept_graph_path),
        )
        if not src_to_atom:
            return {}

        # ② DB 단일 조회 — 원자 code → 원자 행 concept_id(UUID).
        atom_codes = sorted(set(src_to_atom.values()))
        stmt = select(Concept.code, Concept.concept_id).where(Concept.code.in_(atom_codes))
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        code_to_cid = {row.code: row.concept_id for row in rows}

        # ③ 합성 — 원자 행 미적재 src는 제외(orphan skip 경로 유지).
        return {src: code_to_cid[atom] for src, atom in src_to_atom.items() if atom in code_to_cid}

    def populate(self, records: Sequence[ProblemBankRecord]) -> ProblemBankPopulateReport:
        """문제·개념 태깅·계보를 `problem`/`problem_concept`/`problem_relation`에 멱등 upsert.

        ① slug 기준 *마지막 우선* dedup(단일 배치 ON CONFLICT 중복행 오류 방지) → ② 크로스워크
        해석 맵(`{src_id: 원자 행 concept_id}`) 단일 구축 → ③ 각 문제를 `ON CONFLICT(slug) DO
        UPDATE ... RETURNING problem_id`로 적재(problem_id·slug·created_at 미-SET·보존)·안정
        problem_id 획득 → ④ 개념 태깅을 concept_id로 해석(맵에 없으면 orphan skip·집계)·같은
        `(concept_id, role)` 접힘 시 relevance **max**(None 최저 취급) → ⑤ `ON CONFLICT(problem_id,
        concept_id, role) DO UPDATE`로 relevance만 갱신 → ⑥ 같은 트랜잭션에서 해석 집합 밖 기존
        연결 reconcile DELETE(해석 0건이면 그 문제의 연결 전체 삭제 — 구 437 잔재 청소) → ⑦
        계보(S4-18): 이번 배치에서 upsert된 slug→problem_id 맵을 먼저 보고, 없으면 DB를 조회해
        `parent_slug`를 해석(둘 다 실패면 orphan skip·집계 — 참조 무결성). 해석되면
        `problem_relation`을 `ON CONFLICT(parent_problem_id, related_problem_id, relation_type)
        DO UPDATE`로 upsert(similarity_score만 갱신). 반환: 리포트. 빈 입력은 0 리포트(조기 반환).
        """
        if not records:
            return ProblemBankPopulateReport(0, 0, 0, [])

        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.concept import (
            ProblemConcept as ProblemConceptORM,
        )
        from whymath_backend.db.models.problem import Problem as ProblemORM
        from whymath_backend.db.models.problem import (
            ProblemRelation as ProblemRelationORM,
        )

        # ① slug 기준 dedup(마지막 우선) — 단일 배치 ON CONFLICT 중복행 오류 방지.
        by_slug: dict[str, ProblemBankRecord] = {r.slug: r for r in records}
        deduped = list(by_slug.values())

        # ② 개념 해석 맵.
        source_id_to_cid = self._load_source_id_to_concept_id()

        # 문제 갱신 컬럼 집합 — 식별자(problem_id·slug)·생성시각(created_at)은 보존(SET 제외).
        problem_cols = {col.key for col in sa.inspect(ProblemORM).mapper.column_attrs}
        problem_update_keys = problem_cols - {"problem_id", "slug", "created_at"}

        problems_loaded = 0
        problem_concepts_loaded = 0
        reconciled = 0
        relations_loaded = 0
        relations_skipped: list[str] = []
        skipped: list[str] = []
        slug_to_problem_id: dict[str, Any] = {}

        with self._get_engine().begin() as conn:
            for record in deduped:
                # ③ 문제 upsert(slug 충돌) + RETURNING problem_id(안정 식별자 획득).
                payload = record.problem.model_dump()
                values = {k: v for k, v in payload.items() if k in problem_cols}
                insert_stmt = pg_insert(ProblemORM).values(**values)
                problem_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=[ProblemORM.slug],
                    set_={key: insert_stmt.excluded[key] for key in problem_update_keys},
                ).returning(ProblemORM.problem_id)
                problem_id = conn.execute(problem_stmt).scalar_one()
                problems_loaded += 1
                slug_to_problem_id[record.slug] = problem_id

                # ④ 개념 태깅 해석(orphan skip)·같은 (concept_id, role) 접힘 시 relevance max
                #    (None은 최저 취급 — 마지막-우선의 조용한 정보 손실 방지).
                resolved: dict[tuple[Any, str], float | None] = {}
                for tag in record.concept_tags:
                    concept_id = source_id_to_cid.get(tag.concept_src_id)
                    if concept_id is None:
                        skipped.append(
                            f"orphan concept skip(개념 미해석): slug={record.slug} "
                            f"concept_src_id={tag.concept_src_id}"
                            f"(크로스워크 해석 실패 또는 원자 행 미적재) role={tag.role}"
                        )
                        continue
                    key = (concept_id, tag.role)
                    if key in resolved:
                        prev = resolved[key]
                        if prev is None or (tag.relevance is not None and tag.relevance > prev):
                            resolved[key] = tag.relevance
                    else:
                        resolved[key] = tag.relevance

                # ⑤ problem_concept upsert(복합 PK 충돌 시 relevance만 갱신).
                for (concept_id, role), relevance in resolved.items():
                    pc_stmt = pg_insert(ProblemConceptORM).values(
                        problem_id=problem_id,
                        concept_id=concept_id,
                        role=role,
                        relevance=relevance,
                    )
                    pc_stmt = pc_stmt.on_conflict_do_update(
                        index_elements=[
                            ProblemConceptORM.problem_id,
                            ProblemConceptORM.concept_id,
                            ProblemConceptORM.role,
                        ],
                        set_={"relevance": pc_stmt.excluded.relevance},
                    )
                    conn.execute(pc_stmt)
                    problem_concepts_loaded += 1

                # ⑥ reconcile — 이번 해석 집합에 없는 기존 연결 삭제(같은 트랜잭션). upsert-only
                #    로는 원자 재연결 후 구 437 legacy 행이 잔류하므로, 재실행이 곧 정합 회복이
                #    되도록 청소한다. 해석 0건이면 그 문제의 연결 전체 삭제.
                delete_stmt = sa.delete(ProblemConceptORM).where(
                    ProblemConceptORM.problem_id == problem_id
                )
                if resolved:
                    delete_stmt = delete_stmt.where(
                        sa.tuple_(ProblemConceptORM.concept_id, ProblemConceptORM.role).not_in(
                            list(resolved)
                        )
                    )
                delete_result = conn.execute(delete_stmt)
                reconciled += int(getattr(delete_result, "rowcount", 0) or 0)

            # ⑦ 계보(problem_relation) upsert — 이번 배치 전 문제가 upsert된 *이후* 한 번에
            #    처리한다(같은 배치 안에 parent·child가 함께 올 수 있어 slug_to_problem_id가
            #    다 채워진 뒤라야 배치 내 참조도 해석된다).
            for record in deduped:
                if not record.relations:
                    continue
                child_id = slug_to_problem_id[record.slug]
                for rel in record.relations:
                    parent_id = slug_to_problem_id.get(rel.parent_slug)
                    if parent_id is None:
                        row = conn.execute(
                            sa.select(ProblemORM.problem_id).where(
                                ProblemORM.slug == rel.parent_slug
                            )
                        ).first()
                        parent_id = row.problem_id if row is not None else None
                    if parent_id is None:
                        relations_skipped.append(
                            f"orphan relation skip(parent 미해석): slug={record.slug} "
                            f"parent_slug={rel.parent_slug} relation_type={rel.relation_type}"
                        )
                        continue
                    if parent_id == child_id:
                        # 이 upsert는 ORM 직접 경로라 schema.ProblemRelation._no_self_relation을
                        # 거치지 않는다 — 여기서 같은 불변식을 재확인한다(조용한 통과 금지).
                        raise ProblemCorpusError(
                            f"계보 자기관계 금지 위반: slug={record.slug}가 자기 자신을 "
                            f"parent_slug로 선언(parent_slug={rel.parent_slug})"
                        )
                    rel_stmt = pg_insert(ProblemRelationORM).values(
                        parent_problem_id=parent_id,
                        related_problem_id=child_id,
                        relation_type=rel.relation_type,
                        similarity_score=rel.similarity_score,
                    )
                    rel_stmt = rel_stmt.on_conflict_do_update(
                        index_elements=[
                            ProblemRelationORM.parent_problem_id,
                            ProblemRelationORM.related_problem_id,
                            ProblemRelationORM.relation_type,
                        ],
                        set_={"similarity_score": rel_stmt.excluded.similarity_score},
                    )
                    conn.execute(rel_stmt)
                    relations_loaded += 1

        return ProblemBankPopulateReport(
            problems_loaded=problems_loaded,
            problem_concepts_loaded=problem_concepts_loaded,
            concepts_skipped=len(skipped),
            skipped_messages=skipped + relations_skipped,
            problem_concepts_reconciled=reconciled,
            problem_relations_loaded=relations_loaded,
            problem_relations_skipped=len(relations_skipped),
        )


# ──────────────────────────────────────────────────────────────────────────
# 공개 진입점
# ──────────────────────────────────────────────────────────────────────────
def populate_problem_bank(
    session: object | None,
    *,
    problems_path: Path = _DEFAULT_PROBLEMS,
    settings: Settings | None = None,
    store: ProblemBankStore | None = None,
) -> ProblemBankPopulateReport:
    """문제 코퍼스 JSONL을 backend `problem`/`problem_concept`에 멱등 적재. 반환=적재 리포트.

    `load_problem_bank_records`가 authoring 분리·저작권 위생·Problem 검증을 거친 레코드를 만들고,
    `ProblemBankStore.populate`가 slug 충돌 멱등 upsert·concept 해석·orphan skip을 담당한다. store
    미주입 시 슬3 sync 엔진 재사용 store를 만든다(같은 settings 공유).

    `session` 인자는 standards/misconception 로더의 좌석 규약 호환을 위한 *자리표시*다 — 이 적재기는
    sync 엔진으로 동작하므로 ORM async Session을 쓰지 않는다(None 허용). L1→L3 경계상 이 함수는 S2-a
    게이트를 부르지 않는다(코퍼스는 저작 시점에 게이트 통과분·모듈 docstring).

    Raises:
        FileNotFoundError: problems_path 파일 부재.
        ProblemCorpusError: 저작권 위생·안정 키·역할 위반(코퍼스 거부).
        pydantic.ValidationError: 레코드가 Problem 스키마·본문 불변식 위반.
    """
    del session  # async Session 미사용(sync 엔진 좌석) — 호환 자리표시.
    records = load_problem_bank_records(problems_path)
    resolved = settings if settings is not None else get_settings()
    bank_store = store if store is not None else ProblemBankStore(settings=resolved)
    return bank_store.populate(records)


def main(argv: list[str] | None = None) -> int:
    """문제 코퍼스(JSONL)를 `problem`/`problem_concept`에 멱등 적재하고 리포트를 보고(CLI 본체).

    반환은 프로세스 종료 코드(0=성공·2=입력 파일 부재). 적재 로직은 `populate_problem_bank`가
    담당하며 본 함수는 경로 결선·실행·stdout 보고만 한다(조용한 무동작 금지 — 부재 시 명확히 보고).
    """
    parser = argparse.ArgumentParser(
        prog="whymath-problem-bank-populate",
        description=(
            "문제 코퍼스(JSONL) → backend problem·problem_concept 멱등 적재"
            "(slug 충돌 upsert·concept 해석·orphan skip·자체생성 위생)."
        ),
    )
    parser.add_argument(
        "--problems",
        type=Path,
        default=_DEFAULT_PROBLEMS,
        help=f"문제 코퍼스 JSONL 경로(기본 {_DEFAULT_PROBLEMS}).",
    )
    args = parser.parse_args(argv)

    path: Path = args.problems
    if not path.exists():
        print(f"문제 코퍼스 없음: {path} — 코퍼스 생성기(손저작 시드)로 먼저 생성하세요.")
        return 2

    report = populate_problem_bank(None, problems_path=path)
    print(
        f"문제 적재 완료: {report.problems_loaded}건·개념 태깅: "
        f"{report.problem_concepts_loaded}건·reconcile 삭제: "
        f"{report.problem_concepts_reconciled}건 (src={path}). "
        f"개념 orphan skip: {report.concepts_skipped}건"
        + (" (원자 미적재 — l1.atom_graph 선행)." if report.concepts_skipped else ".")
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
