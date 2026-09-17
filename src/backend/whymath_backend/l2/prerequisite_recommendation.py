"""L2 선수개념 추천 — 약개념의 막힌 선수(prerequisite) traversal + mastery + 안전 메타 enrich.

개념그래프 소비 아크의 *선수* 좌석이다. 직전 슬라이스 `recommend_weak_concepts`(약개념 추천)가
"지금 무엇을 복습할지" 약개념을 골랐다면, 이 좌석은 그 약개념의 **선수개념(prerequisite) 중
학습자가 약한 것**을 골라 "*먼저* 복습할 막힌 선수개념"을 돌려준다 — 후행 개념이 안 되는
*근본 원인*이 선수 결손일 수 있기 때문이다(LTHC·선수 진단).

────────────────────────────────────────────────────────────────────────────
선수 traversal 방향 (to == 후행개념 → from == 선수)
────────────────────────────────────────────────────────────────────────────
backend `concept_edge`는 `from_concept_id`가 `to_concept_id`의 *선수*다(`EdgeType.PREREQUISITE`:
"선수 — A를 알아야 B를 안다(A→B)"·적재기 `backend_edge.py` 방향 규약). 따라서 후행 개념 C의
선수를 찾으려면 **`to_concept_id == C AND edge_type == PREREQUISITE`인 행의 `from_concept_id`**를
본다. backend `Concept`에 선수 캐시 컬럼이 없어 `concept_edge`가 유일 경로다(Neo4j 런타임 미도입·
PG 단일 평면). 각 선수의 `code`(UC)·`name_ko`도 `Concept` join으로 가져온다(미측정 선수도
표시·enrich에 UC 필요).

────────────────────────────────────────────────────────────────────────────
다단계(transitive·multi-hop) 선수 traversal — 재귀 CTE (이 슬라이스 확장)
────────────────────────────────────────────────────────────────────────────
직접 선수(1-hop)만으로는 *근본 결손*을 못 짚는다 — 후행이 안 되는 진짜 원인이 "선수의 선수의 …"
여러 단계 아래일 수 있다(LTHC·깊은 선수 체인). 그래서 `fetch_prerequisites`를 `max_depth`로
일반화해 **선수의 선수까지** 따라간다. PG 단일 평면(Neo4j 미도입)이라 **SQLAlchemy Core 재귀
CTE**(`select(...).cte(recursive=True)`·`union_all`·`literal`)로 traversal한다(원시 SQL 0):
  - base(depth=1): `to_concept_id == C AND PREREQUISITE`인 from(직접 선수).
  - recursive(depth+1): `concept_edge JOIN cte ON concept_edge.to_concept_id == cte.concept_id`
    (이전 깊이 선수를 *후행*으로 삼아 한 단계 더)·`WHERE cte.depth < max_depth`(재귀 bound).
  - `max_depth=1`이면 recursive 가지가 `depth < 1`=false라 base만 실행 = **기존 1-hop과 동일**
    (계약 보존).

**DAG 안전**: 선수 그래프는 데이터셋 v1에서 *비순환 보장*이다 —
`data-pipeline/.../concept_graph/validate.py`가 prerequisite 사이클을 hard error
(`prerequisite_cycle`·"순환 선수관계=학습 경로 불능")로 막는다. 따라서 transitive traversal은
자연 종료한다. 그래도 **방어적으로 `max_depth` 상한**으로 재귀를 bound한다(부분 적재·미래 데이터
대비). 같은 선수가 여러 경로/깊이로 나오면 Python에서 **MIN depth** 1건만 유지하고(가장 가까운
경로), origin 개념 C 자체는 결과에서 제외한다(DAG라 안 나오지만 방어적).

────────────────────────────────────────────────────────────────────────────
원자 축 울타리 (ARCH-13 — 이중 진실 조인 해소)
────────────────────────────────────────────────────────────────────────────
`concept`/`concept_edge`에는 원자 백본(runtime truth)과 구 437 개념(legacy_snapshot)이 **code로
병존**한다(MEMORY S0-1). 그래서 traversal 결과에는 두 축이 섞여 나올 수 있다. 과거에는 그 code를
*별도 sync 엔진*으로 들고 가 `atom_node`에 문자열 조인했고, 축이 어긋나면 미스→enrich None이 됐다가
`reviewed_only`에서 **조용히 탈락**했다(무엇이 왜 빠졌는지 관측 불가).

이 좌석은 그 지점을 다음으로 대체한다:
  - **축 판정을 쿼리 안으로**: traversal 최종 SELECT가 `atom_axis_outerjoin`으로 `atom_node`를
    LEFT OUTER JOIN하고 안전 메타 3열을 함께 가져온다 — 축 판정도 메타도 **한 쿼리·한 엔진**
    (교차 엔진 code 문자열 조인 소멸).
  - **축 밖은 항상 제외**: `atom_meta is None`(=축 밖)이면 `reviewed_only` 값과 무관하게 뺀다.
    runtime truth=원자 단일이라는 S0-4 전제의 직접 표현이다.
  - **제외는 세어서 표면화**: 축 밖·미검수·비약점을 `AxisExclusions`로 분리 계상하고 구조화 로그로
    남긴다(침묵 실패 금지). 세부 결과가 필요하면 `recommend_prerequisite_gaps_detailed`를 쓴다.

────────────────────────────────────────────────────────────────────────────
재사용 좌석 (신규 진단·정렬 로직 0)
────────────────────────────────────────────────────────────────────────────
① mastery — `l2.concept_diagnosis.compute_concept_diagnoses`를 *한 번* 호출해 `{concept_id:
   diagnosis}` 맵으로 선수들의 BKT/IRT 숙달을 조회한다(약개념 추천과 동일 좌석·신규 0). 측정 없는
   선수는 맵에 없어 mastery None(graceful).
② code enrich — `l1.atom_graph.axis`(원자 축 async 좌석)의 `atom_axis_outerjoin`·
   `atom_meta_from_row`를 traversal 쿼리에서 그대로 쓴다. 메타 타입은 기존 `AtomNodeMeta`
   재사용(신규 값객체 0).

────────────────────────────────────────────────────────────────────────────
redaction·노출 계약 (CLAUDE.md 우선순위 #2 — 협상 불가)
────────────────────────────────────────────────────────────────────────────
enrich되는 건 *안전 표시·게이팅 필드*뿐(name_ko·subject_area·review_status). **description·
formal_definition·core_proposition은 어디에도 유입되지 않는다** — `atom_node`·`Concept`
조회 컬럼에 본문이 없고, `PrerequisiteGap` 스키마에 *슬롯 자체가 없다*(삼중 방어). 이 좌석은
학생 직접 노출이 아니라 *내부 조회 좌석*이다(소비 슬 일관). `reviewed_only` 게이팅은 약개념
추천과 동일 규약(reviewed만·검수 전이면 보수적 제외).

7계층: L2 학습자 모델이 L1 데이터(concept_edge ORM·원자 축 좌석 `l1.atom_graph.axis`)를
*조회*(L_n→L_{n-1} 허용·원자 축도 동일 방향). ORM 쿼리빌더만(원시 SQL 0). L4 코칭·L5 노출은 부착
하지 않는다(역방향 의존 회피). 선수 traversal의 방향·재귀 CTE 계약은 이 전환에서 불변이다 —
바뀐 것은 같은 쿼리에 축 조인이 하나 붙은 것뿐(데이터 변경·rekey 0).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept import Concept, ConceptEdge
from whymath_backend.l1.atom_graph.atom_node_projection import AtomNodeMeta
from whymath_backend.l1.atom_graph.axis import (
    ATOM_AXIS_META_COLUMNS,
    atom_axis_outerjoin,
    atom_meta_from_row,
)
from whymath_backend.l2.axis_exclusions import AxisExclusions, log_axis_exclusions
from whymath_backend.l2.concept_diagnosis import (
    Agreement,
    ConceptDiagnosis,
    compute_concept_diagnoses,
)
from whymath_backend.l2.recommendation_contract import WEAK_CONCEPT_MASTERY_CEILING
from whymath_backend.schema.enums import EdgeType

if TYPE_CHECKING:
    from sqlalchemy.sql.selectable import Select

# 검수 게이팅 비교 리터럴 — 약개념 추천(`weak_concept_recommendation._REVIEWED`)과 동일 규약.
_REVIEWED: str = "reviewed"

# 구조화 로그·집계 좌석명(`whymath.l2.<seat>` 로거로 나간다).
_SEAT: str = "prerequisite_recommendation"

# 선수 traversal 최대 깊이 — *단일 출처*(math_dsl_risk_register.md Q10-⑧). 선수 그래프는 DAG
# 보장(data-pipeline validate.py prerequisite_cycle hard error)이라 재귀는 자연 종료하나, 비용·
# 노이즈를 막으려 상한으로 bound한다(부분 적재·미래 데이터 대비 방어). API 경계(`api/me.py`
# MaxDepth)가 이 상한을 공유해 매직 넘버 중복을 없앤다.
# ⚠️ 이것은 *그래프 traversal 깊이 예산*이지 "LLM 컨텍스트 예산"(max_nodes·max_tokens)이 아니다.
# 후자(Q10-⑧ Minimal Reasoning Subgraph 예산 guard)는 LLM에 subgraph를 주입하는 소비처가 생긴 뒤
# canonical seam(`l2/reasoning_subgraph.py`)으로 신설한다(지금 미존재·premature — risk_register
# 미채택·build_roadmap_part10_review §4). 그 seam 전까지 "전체 그래프 미열람" 경계는 거버넌스
# 테스트 `tests/backend/l3/test_llm_subgraph_budget_invariant.py`로 CI 동결돼 있다.
MAX_PREREQUISITE_DEPTH: int = 5

# 선수 traversal 노드 수(breadth) 상한 — *단일 출처*. `MAX_PREREQUISITE_DEPTH`가 *깊이*를
# bound하면 이것은 최종 반환 선수 *개수*를 bound하는 안전밸브다(재귀 CTE는 깊이당 fan-out이
# 무제한이라 depth 상한만으로는 breadth 폭발을 못 막는다). 현재 규모(out-degree 평균 낮음·직접
# 선수 소수)에선 절대 발동하지 않아 행동 변화 0이고, 규모 확장(hub 노드 out-degree↑·max_depth
# 상향)에서 재귀 CTE 결과가 병리적으로 폭증해 다운스트림(mastery 조회·enrich)을 오염시키는 것만
# 차단한다. 초과 절단은 *조용히 하지 않고* 로그로 남긴다(silent truncation 금지 — CLAUDE.md
# "AI·신뢰" 축 원칙).
# ⚠️ 이것은 *그래프 traversal 예산*이지 "LLM 컨텍스트 예산"(max_tokens)이 아니다 — 그 경계는
# build_roadmap_part10_review.md §4가 별도로 다루며(소비처 부재·premature·미채택), 이 상수와는
# 독립이다.
MAX_PREREQUISITE_NODES: int = 64

_logger = logging.getLogger(f"whymath.l2.{_SEAT}")


def _cap_by_node_budget(
    rows: list[PrerequisiteRow], *, cap: int = MAX_PREREQUISITE_NODES
) -> list[PrerequisiteRow]:
    """선수 traversal 결과를 노드 수 예산으로 bound — 초과 시 상위 `cap`만 유지하고 드롭 수를 로깅.

    입력 `rows`는 이미 결정론 정렬(depth asc→edge_strength desc→concept_id)·dedup된 최종 목록이라
    상위 `cap`은 "가장 가깝고 강한 선수"다(weakness 재정렬은 호출부 `recommend_prerequisite_gaps`라
    여기선 구조 근접 우선을 보존한다). 현재 규모에선 `len(rows) <= cap`라 절단 0(행동 불변). 절단이
    실제로 일어나면 조용히 넘기지 않고 warning으로 드롭 수를 남긴다(규모 도달 관측 신호). 순수
    함수(리스트 in→리스트 out·부수효과=로그뿐)라 DB 없이 단위테스트한다.
    """
    if len(rows) <= cap:
        return rows
    _logger.warning(
        "선수 traversal 노드 예산 초과 — %d개 중 상위 %d개만 유지(드롭 %d)",
        len(rows),
        cap,
        len(rows) - cap,
    )
    return rows[:cap]


@dataclass(frozen=True, slots=True)
class PrerequisiteRow:
    """선수 traversal 단일 결과 — 선수 concept_id(UUID)·code(UC)·name_ko·edge_strength·depth.

    `concept_edge`(to==후행) join `concept`(from-side) 조회 한 행이다. mastery·enrich 부착 전
    *그래프 구조* 값만 담는다(선수 식별 + 선수관계 강도 + 선수 거리). 별도 dataclass로 빼
    traversal 조회를 단위테스트에서 패치 가능하게 한다(실 SQL 격리). `depth`는 1=직접 선수·
    2=선수의 선수…(다단계 traversal의 hop 수). 같은 선수가 여러 경로로 나오면 MIN depth만 유지.
    """

    concept_id: uuid.UUID  # 선수개념 backend UUID(from_concept_id)
    concept_code: str | None  # 선수개념 UC(concept.code·orphan이면 None)
    name_ko: str | None  # 선수개념 한국어명(concept.name_ko)
    edge_strength: float | None  # 선수관계 강도(edge_strength·미기재 None)
    depth: int = 1  # 선수 거리(1=직접 선수·2=선수의 선수…·MIN depth 유지)
    # 원자 축 안전 메타(같은 쿼리 LEFT OUTER JOIN 산출). **None = 원자 축 밖**(구 437 등) —
    # "메타가 아직 없는 원자"가 아니다(ARCH-13·`l1/atom_graph/axis.py` docstring).
    atom_meta: AtomNodeMeta | None = None


class PrerequisiteGap(BaseModel):
    """막힌 선수개념 1건 — 선수 traversal + BKT/IRT 약점 + atom_node 안전 메타 enrich.

    약개념 C의 선수개념 중 학습자가 약한(막힌) 것이다. `weakness`는 비교 가능한 두 신호
    (bkt_mastery·irt_mastery_proxy) 중 *최저값*(약점 정렬·필터 기준). 측정 없는 선수는 두 신호·
    weakness 모두 None(agreement="insufficient"). `domain`·`review_status`·`name_ko`는
    `atom_node`(code) 조인 *안전 표시·게이팅 필드*(메타 미적재면 None graceful·S0-4d·runtime
    truth=원자). `edge_strength`는 선수관계 강도(강한 선수일수록 후행에 결정적). **본문
    (description·formal_definition·core_proposition)은 미포함** — 조회 컬럼·스키마에 슬롯이 없어
    구조적으로 흐를 수 없다(redaction·노출 계약).
    """

    concept_id: uuid.UUID = Field(description="선수개념 id(backend `concept` UUID PK).")
    concept_code: str | None = Field(
        default=None, description="선수개념 코드(=UC·개념그래프 키). orphan이면 null."
    )
    concept_name: str | None = Field(
        default=None, description="선수개념명(backend `concept`.name_ko). orphan이면 null."
    )
    bkt_mastery: float | None = Field(
        default=None, description="선수개념 BKT 최신 숙달 P(L). 측정 없으면 null."
    )
    irt_mastery_proxy: float | None = Field(
        default=None, description="logistic(θ)∈[0,1] — 선수개념 IRT 능력 프록시. θ 없으면 null."
    )
    weakness: float | None = Field(
        default=None,
        description="두 신호(bkt_mastery·irt_mastery_proxy) 중 최저값(막힘 정도·정렬 기준). "
        "측정 신호가 없으면 null(weak_only=true면 제외).",
    )
    agreement: Agreement = Field(
        description="BKT↔IRT 일치 신호(agree·irt_higher·bkt_higher·insufficient). "
        "측정 없는 선수는 insufficient."
    )
    domain: str | None = Field(
        default=None,
        description="선수개념 영역명(atom_node 조인·안전 표시 필드). 필드명은 계약 안정을 위해 "
        "`domain`을 유지하나, 값 소스는 이제 원자 `subject_area`다(S0-4d·runtime truth=원자). "
        "메타 미적재 시 null.",
    )
    review_status: str | None = Field(
        default=None,
        description="검수 상태('reviewed'/'pending'·atom_node 조인·게이팅 플래그). "
        "메타 미적재 시 null.",
    )
    name_ko: str | None = Field(
        default=None,
        description="선수개념 한국어 표시명(atom_node 조인·안전 표시 필드). 미적재 시 null.",
    )
    edge_strength: float | None = Field(
        default=None,
        description="선수관계 강도 [0,1](concept_edge.edge_strength·강한 선수일수록 결정적). "
        "미기재 시 null.",
    )
    depth: int = Field(
        default=1,
        description="선수 거리 — 1=직접 선수·2=선수의 선수…(다단계 traversal hop 수). "
        "여러 경로로 닿으면 가장 가까운(MIN) 거리. 그래프 구조 메타(안전·본문 아님).",
    )


@dataclass(frozen=True, slots=True)
class PrerequisiteRecommendation:
    """선수개념 추천 결과 + **제외 사유 집계** — 빈 결과의 이유를 알 수 있게 하는 반환형.

    `gaps`만 필요한 호출자는 얇은 래퍼 `recommend_prerequisite_gaps`를 쓴다(기존 계약 불변).
    빈 `gaps`를 받았을 때 "선수가 없다"·"전부 숙달했다"·"축 밖이라 버려졌다"를 구분하려면
    `exclusions`를 본다(ARCH-13 표면화).
    """

    gaps: list[PrerequisiteGap]
    exclusions: AxisExclusions


def _weakness_of(diagnosis: ConceptDiagnosis) -> float | None:
    """비교 가능한 신호(bkt_mastery·irt_mastery_proxy) 중 최저값 — 둘 다 없으면 None.

    약개념 추천(`weak_concept_recommendation._weakness_of`)과 *동일 정의*(최저 신호 = 약점).
    측정 신호가 하나도 없으면 None(weak_only면 호출부가 제외).
    """
    signals = [v for v in (diagnosis.bkt_mastery, diagnosis.irt_mastery_proxy) if v is not None]
    return min(signals) if signals else None


def build_prerequisite_stmt(concept_id: uuid.UUID, max_depth: int) -> Select[Any]:
    """선수 traversal 재귀 CTE + **원자 축 LEFT OUTER JOIN** statement 조립(실행 없음).

    `fetch_prerequisites`에서 분리해 둔 이유는 두 가지다: ①축 울타리가 *쿼리 안*에 있다는 사실을
    DB 없이 검증할 수 있게(컴파일 SQL 거버넌스 테스트) ②조립과 실행의 관심사 분리.

    SELECT 목록 = 구조 5열(concept_id·code·name_ko·edge_strength·depth) + 원자 축 안전 메타 3열
    (`ATOM_AXIS_META_COLUMNS`). 조인 키는 `concept.code ↔ atom_node.code`(동일 code 공간).
    """
    # base 앵커(depth=1) — C의 직접 선수(to==C→from). recursive와 union하려 CTE로 만든다.
    base = (
        select(
            ConceptEdge.from_concept_id.label("concept_id"),
            ConceptEdge.edge_strength.label("edge_strength"),
            literal(1).label("depth"),
        )
        .where(
            ConceptEdge.to_concept_id == concept_id,
            ConceptEdge.edge_type == EdgeType.PREREQUISITE.value,
        )
        .cte(name="prereq_traversal", recursive=True)
    )
    # recursive 가지(depth+1) — 이전 깊이 선수(cte.concept_id)를 *후행*으로 삼아 그 선수를 한 단계
    # 더. `cte.depth < max_depth`로 bound(max_depth=1이면 false라 base만 = 1-hop 계약 보존).
    recursive = (
        select(
            ConceptEdge.from_concept_id.label("concept_id"),
            ConceptEdge.edge_strength.label("edge_strength"),
            (base.c.depth + 1).label("depth"),
        )
        .join(base, ConceptEdge.to_concept_id == base.c.concept_id)
        .where(
            ConceptEdge.edge_type == EdgeType.PREREQUISITE.value,
            base.c.depth < max_depth,
        )
    )
    traversal = base.union_all(recursive)
    # 최종 SELECT — cte를 Concept join(concept_id→code·name_ko) 후 원자 축 OUTER JOIN(메타 3열).
    # 안정 정렬(depth asc→강도 desc→concept_id)로 dedup MIN depth 선택을 결정론적으로 만든다.
    stmt = select(
        traversal.c.concept_id,
        Concept.code,
        Concept.name_ko,
        traversal.c.edge_strength,
        traversal.c.depth,
        *ATOM_AXIS_META_COLUMNS,
    ).join(Concept, traversal.c.concept_id == Concept.concept_id)
    stmt = atom_axis_outerjoin(stmt, Concept.code)
    return stmt.order_by(
        traversal.c.depth.asc(),
        traversal.c.edge_strength.desc().nullslast(),
        traversal.c.concept_id,
    )


async def fetch_prerequisites(
    session: AsyncSession, concept_id: uuid.UUID, *, max_depth: int = 1
) -> list[PrerequisiteRow]:
    """후행 개념 C의 선수개념들을 `concept_edge`(to==C·PREREQUISITE) **재귀 CTE** traversal로 조회.

    **방향**: `to_concept_id == concept_id AND edge_type == PREREQUISITE`인 행의
    `from_concept_id`(선수)가 직접 선수다(depth=1). `max_depth>1`이면 그 선수를 다시 *후행*으로
    삼아 "선수의 선수…"까지 따라간다(depth 2·3…). 각 선수의 `code`(UC)·`name_ko`는 `Concept`
    join으로 함께 가져온다(미측정 선수도 표시·enrich에 UC 필요).

    **재귀 CTE 구조**(SQLAlchemy Core·원시 SQL 0):
      - base(depth=1): `to_concept_id == concept_id AND PREREQUISITE`인 from·edge_strength·
        `literal(1)` as depth.
      - recursive(depth+1): `concept_edge JOIN cte ON concept_edge.to_concept_id == cte.concept_id`
        (이전 깊이 선수를 후행으로)·같은 edge_type 필터·**`WHERE cte.depth < max_depth`**(bound).
        새 행 = from·edge_strength·`cte.depth + 1`.
      - `base.union_all(recursive)` → cte. **`max_depth=1`이면 recursive가 `depth < 1`=false라
        base만 = 기존 1-hop과 동일**(계약 보존).

    **dedup**: 같은 선수가 여러 경로/깊이로 나올 수 있어(DAG의 diamond) Python에서 **MIN depth**
    1건만 유지한다(동률 깊이면 edge_strength 큰 것·결정론). origin C 자체는 제외(DAG라 안 나오나
    방어적). 정렬은 호출부(`recommend_prerequisite_gaps`)가 weakness 기준으로 다시 하므로 여기선
    안정적 순서(depth asc·edge_strength desc·concept_id)만 보장한다.

    **원자 축 메타 동승**(ARCH-13): 최종 SELECT가 `atom_node`를 LEFT OUTER JOIN해 안전 메타 3열을
    함께 가져온다 — 각 행의 `atom_meta`가 `None`이면 그 선수는 **원자 축 밖**이다(별도 엔진 왕복 0).

    DAG 보장(validate.py prerequisite_cycle hard error)이라 재귀는 자연 종료하나, `max_depth`로
    방어적으로 bound한다(부분 적재·미래 데이터 대비). 실 SQL이라 단위테스트는 이 함수를 패치한다.

    **breadth 안전밸브**: dedup 이후 최종 목록에 `MAX_PREREQUISITE_NODES` 상한을 적용한다
    (`_cap_by_node_budget`) — `max_depth`가 깊이를, 이것이 노드 *개수*를 bound한다.
    """
    rows = (await session.execute(build_prerequisite_stmt(concept_id, max_depth))).all()

    # dedup — 같은 선수가 여러 경로/깊이로 나오면 MIN depth 1건만(정렬이 depth asc라 첫 등장이
    # MIN depth·동률이면 강도 큰 것). origin C 자체는 방어적으로 제외(DAG라 안 나오나 안전).
    seen: set[uuid.UUID] = set()
    result: list[PrerequisiteRow] = []
    for cid, code, name, strength, depth, meta_name, meta_area, meta_review in rows:
        if cid == concept_id or cid in seen:
            continue
        seen.add(cid)
        result.append(
            PrerequisiteRow(
                concept_id=cid,
                concept_code=code,
                name_ko=name,
                edge_strength=float(strength) if strength is not None else None,
                depth=int(depth),
                atom_meta=atom_meta_from_row(meta_name, meta_area, meta_review),
            )
        )
    # breadth 안전밸브 — dedup 이후 최종 목록에 노드 수 예산을 적용(MIN-depth 선택 왜곡 없음).
    # 현재 규모 미발동(행동 불변)·규모 폭발만 차단·초과 시 로깅(silent 금지).
    return _cap_by_node_budget(result)


async def recommend_prerequisite_gaps_detailed(
    session: AsyncSession,
    user_id: uuid.UUID,
    concept_id: uuid.UUID,
    *,
    mastery_threshold: float = WEAK_CONCEPT_MASTERY_CEILING,
    reviewed_only: bool = False,
    weak_only: bool = True,
    max_depth: int = 1,
) -> PrerequisiteRecommendation:
    """약개념 C의 선수개념 중 *막힌*(약한) 것 → mastery·메타 enrich → 정렬 추천(선수 복습 우선).

    흐름:
      ① **선수 traversal** — `fetch_prerequisites(max_depth=max_depth)`로 C의 선수개념(to==C·
         PREREQUISITE의 from)들 + code(UC)·name_ko·edge_strength·depth를 조회한다. `max_depth=1`
         (기본)이면 직접 선수만(기존 1-hop 계약·후방 호환)·`max_depth>1`이면 "선수의 선수…"까지
         다단계로 따라간다(근본 결손이 여러 단계 아래일 수 있음·LTHC). 미측정 선수도 포함.
      ② **mastery 조회** — `compute_concept_diagnoses`를 *한 번* 호출해 `{concept_id: diagnosis}`
         맵으로 선수들의 BKT/IRT 숙달을 lookup한다(없으면 None·insufficient·graceful).
      ③ **weak_only**(기본 True) — weakness(두 신호 최저)가 `mastery_threshold` *미만*인 선수만
         (= 막힌). weakness None(미측정)은 weak_only=True면 제외(약점 근거 없음)·False면 포함.
         weak_only=False면 모든 선수(약점 무관). 제외분은 `not_weak`로 계상.
      ④ **원자 축 울타리**(ARCH-13) — traversal이 이미 붙여 온 `row.atom_meta`가 `None`이면 그
         선수는 원자 축 밖(구 437 등)이다. runtime truth=원자 단일이므로 `reviewed_only` 값과
         **무관하게 제외**하고 `off_atom_axis`로 계상한다(별도 엔진 조회 0·조용한 탈락 0).
      ⑤ **reviewed_only 게이팅** — True면 `review_status == "reviewed"`인 선수만. 축 안이지만
         검수 전인 제외분은 `not_reviewed`로 계상한다(④와 사유가 섞이지 않는다). 기본 False는
         recall 보존.
      정렬: weakness 오름차순(가장 약한 선수 = root blocker 먼저)·weakness None은 뒤·동률은
      **depth asc**(가까운 선수 먼저 — 더 직접 실행 가능)·그 다음 edge_strength desc(강한 선수
      우선·None 뒤)·concept_id로 결정론. 각 깊이의 선수는 mastery·weak_only·울타리·게이팅을
      *모두 동일하게* 처리한다(깊이는 정렬 tie-break에만 관여·필터링엔 무관).

    반환은 `gaps` + `exclusions`(제외 사유별 건수)다 — 빈 결과의 이유를 호출자가 구분할 수 있게
    한다. 제외가 있으면 구조화 로그도 1줄 남긴다(카운트만·식별 정보 0).

    user_id 스코핑·읽기 전용(마이그레이션 0). enrich되는 건 안전 필드뿐 —
    본문(description·formal_definition·core_proposition)은 컬럼·스키마에 슬롯이 없어 구조적으로
    0(redaction·노출 계약). 선수 traversal(`concept_edge`)·mastery 파생·`concept_code` 키 축은
    불변 — 메타는 같은 쿼리의 원자 축 OUTER JOIN에서 온다(rekey 0·데이터 변경 0).
    """
    # ① 선수 traversal(to==C → from·재귀 CTE·max_depth bound·미측정 포함). max_depth=1이면
    # base만 = 직접 선수(기존 1-hop 계약)·>1이면 선수의 선수…(다단계).
    prerequisites = await fetch_prerequisites(session, concept_id, max_depth=max_depth)
    if not prerequisites:
        return PrerequisiteRecommendation(gaps=[], exclusions=AxisExclusions())

    # ② mastery 조회 — 학습자 진단 *한 번* 호출 → concept_id 맵(측정 없는 선수는 부재).
    diagnoses = await compute_concept_diagnoses(session, user_id)
    diag_by_id: dict[uuid.UUID, ConceptDiagnosis] = {d.concept_id: d for d in diagnoses}

    # ③ weak_only 필터 — 막힌 선수만(weakness < 임계). 미측정(weakness None)은 weak_only면 제외.
    off_atom_axis = 0
    not_reviewed = 0
    not_weak = 0
    kept: list[tuple[PrerequisiteRow, ConceptDiagnosis | None, float | None]] = []
    for row in prerequisites:
        diag = diag_by_id.get(row.concept_id)
        weakness = _weakness_of(diag) if diag is not None else None
        if weak_only and (weakness is None or weakness >= mastery_threshold):
            not_weak += 1  # 미측정(근거 없음) 또는 임계 이상(안 막힘) → 제외.
            continue
        kept.append((row, diag, weakness))

    # ④/⑤ 축 울타리 + 게이팅 + 조립 — 축 밖은 항상 제외, 검수 미완은 reviewed_only일 때만 제외.
    #     두 사유를 분리 계상해 "왜 비었나"를 호출자가 구분할 수 있게 한다(ARCH-13 표면화).
    gaps: list[PrerequisiteGap] = []
    for row, diag, weakness in kept:
        node: AtomNodeMeta | None = row.atom_meta
        if node is None:
            # 원자 축 밖 — runtime truth=원자 단일이므로 reviewed_only 값과 무관하게 제외한다.
            off_atom_axis += 1
            continue
        if reviewed_only and node.review_status != _REVIEWED:
            not_reviewed += 1  # 축 안이지만 검수 전(확인 불가) → 보수적 제외.
            continue
        gaps.append(
            PrerequisiteGap(
                concept_id=row.concept_id,
                concept_code=row.concept_code,
                concept_name=row.name_ko,
                bkt_mastery=diag.bkt_mastery if diag is not None else None,
                irt_mastery_proxy=diag.irt_mastery_proxy if diag is not None else None,
                weakness=weakness,
                agreement=diag.agreement if diag is not None else "insufficient",
                # DTO 필드명 `domain`은 유지(계약 안정)·값 소스는 원자 subject_area(S0-4d).
                domain=node.subject_area,
                review_status=node.review_status,
                name_ko=node.name_ko,
                edge_strength=row.edge_strength,
                depth=row.depth,
            )
        )

    # 정렬 — weakness asc(가장 약한 선수=root blocker 먼저)·None은 뒤·동률은 depth asc(가까운
    # 선수 먼저·더 직접 실행 가능)·그 다음 edge_strength desc(강한 선수 우선·None 뒤)·concept_id.
    def _sort_key(gap: PrerequisiteGap) -> tuple[float, int, float, str]:
        weak = gap.weakness if gap.weakness is not None else float("inf")
        # edge_strength desc → 음수화(None은 가장 약하게 뒤로 = +inf의 음수 = -inf 대신 0 처리).
        strength = -gap.edge_strength if gap.edge_strength is not None else float("inf")
        return (weak, gap.depth, strength, str(gap.concept_id))

    gaps.sort(key=_sort_key)
    exclusions = AxisExclusions(
        off_atom_axis=off_atom_axis, not_reviewed=not_reviewed, not_weak=not_weak
    )
    log_axis_exclusions(_SEAT, exclusions, kept=len(gaps))
    return PrerequisiteRecommendation(gaps=gaps, exclusions=exclusions)


async def recommend_prerequisite_gaps(
    session: AsyncSession,
    user_id: uuid.UUID,
    concept_id: uuid.UUID,
    *,
    mastery_threshold: float = WEAK_CONCEPT_MASTERY_CEILING,
    reviewed_only: bool = False,
    weak_only: bool = True,
    max_depth: int = 1,
) -> list[PrerequisiteGap]:
    """`recommend_prerequisite_gaps_detailed`의 `gaps`만 돌려주는 얇은 래퍼(기존 계약 보존).

    제외 사유 집계까지 필요한 호출자만 `_detailed`를 쓴다 — 로직 중복 0(본체는 하나).
    """
    result = await recommend_prerequisite_gaps_detailed(
        session,
        user_id,
        concept_id,
        mastery_threshold=mastery_threshold,
        reviewed_only=reviewed_only,
        weak_only=weak_only,
        max_depth=max_depth,
    )
    return result.gaps


__all__ = [
    "MAX_PREREQUISITE_DEPTH",
    "MAX_PREREQUISITE_NODES",
    "PrerequisiteGap",
    "PrerequisiteRecommendation",
    "PrerequisiteRow",
    "build_prerequisite_stmt",
    "fetch_prerequisites",
    "recommend_prerequisite_gaps",
    "recommend_prerequisite_gaps_detailed",
]
