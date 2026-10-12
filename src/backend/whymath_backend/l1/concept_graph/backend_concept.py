"""[LEGACY_SNAPSHOT · non_runtime · audit_only] 구 437 격하(S0-4b).

런타임 truth source는 원자 백본(atom_graph_v1). 이 모듈은 audit·빌드타임 provenance이며 런타임
호출자 0(api·l2·l3·l4 구 437 reader 0). 물리 삭제 0·형식 격하만(S0-4b).

개념그래프 → backend 런타임 `Concept` ORM 적재 — UC↔UUID 브리지(개념그래프 소비 *브리지* 슬1).

L1 개념그래프 *소비* 트랙의 **브리지 슬라이스**다. 적재 아크(슬1~4)·소비 슬1(슬117)이 개념을
Neo4j(슬2)·pgvector `concept_embedding`(슬3)·`concept_node`(슬117) **세 투영에 UC 키**로 적재했지만,
*런타임 개념 엔티티* backend `concept` 테이블(UUID PK·`code` unique)은 **비어 있고 UC와 미연결**이다
(`concept_node` 모듈 docstring: "backend PG `concept` 테이블[UUID PK+code]과는 *여전히 별개*다").
런타임 소비처 — L2 `mastery_tracking`(concept_mastery_history.concept_id=UUID)·`problem_concept`
(concept_id=UUID FK)·L4 coach — 는 backend `concept` UUID를 참조하므로, 개념그래프가 런타임에서
보이지 않는다.

이 모듈이 그 다리를 놓는다(**결정 A**): `graph.json`의 개념을 backend `Concept` ORM 행으로 적재하되
**`code`=UC**(concept_id)로 둔다. 그러면 한 논리키 UC가 *사중 store*(Neo4j 그래프·pgvector 벡터·
`concept_node` 메타·backend `concept` 런타임 UUID)를 잇고, 런타임 경로가 닫힌다:
L2 mastery(UUID concept) → `concept.code`(UC) → `concept_node`/`concept_embedding`/Neo4j 도달.

────────────────────────────────────────────────────────────────────────────
redaction (CLAUDE.md 우선순위 #2 — 협상 불가)
────────────────────────────────────────────────────────────────────────────
backend `Concept`의 `description`·`formal_definition`·`intuitive_explanation`·
`common_misconceptions`는 2026-07-03 Part 2 리치 채택 **Phase 1b로 런타임 노드에서 제거**됐다
(컬럼 자체 부재·마이그레이션 동반). 앞 3개는 *검수 책임 자유 서술*(성취기준·교과서 본문 근접·
redaction)이고 graph.json에도 부재이며, 마지막은 자유텍스트 오개념 리스트(낙인·즉답·날조 위험)라
identity 노드에 내장하지 않는다. 정본: 자체작성 교수 텍스트는 정본 identity 노드 semantic 계층
(intuition·representations)·ConceptContent가, 오개념은 검증된 *카탈로그*(`MisconceptionCatalog`·
kebab-id)·활성 가설이 단일 진실이다(CLAUDE.md #6). 이 적재기는 넷 다 *읽지도 채우지도 않는다* —
컬럼이 없어 구조적으로 재유입이 차단된다(4중 방어). 네 컬럼 모두 소비처 0·전량 NULL/`[]`이었다.

────────────────────────────────────────────────────────────────────────────
필드 매핑 (graph.json Concept → backend Concept)
────────────────────────────────────────────────────────────────────────────
직결:
  - `concept_id`(재ID 후 `math.<area>.<slug>`·예 'math.calculus.geukhan') → **`code`**(브리지 키·
    UNIQUE). `name_ko`는 이제 노드가 아니라 `locales/ko.json`(concept_id 조인)에서 소싱한다(P2d).
    이 적재기는 concept_id를 *형식 불문* opaque str로 code에 그대로 넣으므로 옛 `{TRACK}-{AREA}-
    {NNN}`·옛 UC·새 canonical 모두 별도 변경 없이 흐른다.
  - `source_id`(재ID 전 원천 src_id) → `source_id`(추적성 보존·옛 graph.json엔 부재→None).
  - `aliases`([레거시 UC, src_id]) → `aliases`(옛 키 join 보존·옛 graph.json엔 부재→빈 배열).
유도(소스 신호가 깔끔히 대응할 때만):
  - `intrinsic_difficulty`[1,5] ← `difficulty_tier`[0,24] 선형 스케일(0→1.0·24→5.0).
필수 NOT NULL인데 소스 부재 → 보수 유도:
  - `level`(NOT NULL `concept_level_enum`) ← **`세부개념`**(고정). graph 403개는 전부 세부 개념
    노드(단원·소단원 위계가 아니라 평면 개념 목록)라 *교수학적으로 정확한* 유도다(날조 아님).
    'unspecified' enum 값 추가·nullable화 같은 스키마 변경을 피한다(마이그레이션 0).
미매핑(NULL/기본 유지·교수학 내용 날조 금지):
  - `name_en`·`parent_concept_id`·`is_signature_korean`(기본 False)·`cognitive_type`·
    `exam_frequency`·`weight_in_curriculum` — 소스에 합당한 대응 없음 → 검수 대기. (본문 3종·오개념
    컬럼은 Phase 1b로 아예 제거됨 — 위 redaction. `recommended_visual_styles`는 ARCH-14 ③으로
    전용 Overlay `concept_visual_style`로 이관돼 노드 컬럼 자체가 없다 — 구조적 미매핑 해소.)
  (`aliases`·`source_id`는 더는 미매핑이 아니다 — 재ID(2026-06-16)로 graph.json이 둘을 산출하므로
  직결 적재한다. 옛 graph.json(둘 다 부재)도 None/빈 배열로 graceful.)

graph의 `grade_band_hint`·`standard_codes`·`ccss_code`·`metaphor`·`accepted_expressions`·
`review_status`·`prerequisite_concept_ids`·`misconception_codes`·`visualization_card_keys`·`notes`는
backend `Concept` 스키마에 *대응 컬럼이 없다* — `concept_node`(슬117) 프로젝션이 그 메타를 UC 키로
이미 보관하므로, 이 런타임 엔티티엔 *런타임 결선에 필요한 최소 식별*(code=UC·name_ko·
난이도)만 적재한다(이중 보관 회피·후속 consolidation 후보 — 보고 ⑥).

────────────────────────────────────────────────────────────────────────────
멱등 (UC 충돌 upsert·UUID PK 보존)
────────────────────────────────────────────────────────────────────────────
`code`(UC)가 UNIQUE라 `INSERT ... ON CONFLICT(code) DO UPDATE`로 멱등 적재한다 — 같은 UC 재적재는
*기존 행을 갱신*하고 **UUID PK를 보존**한다(신규 행만 `gen_random_uuid()` server_default로 발급).
이는 결정적이다: L2 mastery·problem_concept이 이미 그 UUID를 참조 중일 수 있으므로 재적재가
UUID를 바꾸면 안 된다. ON CONFLICT는 PK(concept_id)를 SET하지 않아 보존된다.

403 전량 적재(`review_status` 무관 — 게이팅은 조회 몫·슬2/3/117 동형). 본 적재기는 *런타임 엔티티*
존재를 보장할 뿐, 노출 게이팅은 소비처(검색 `reviewed_only`·L2/L4)가 건다.

────────────────────────────────────────────────────────────────────────────
재-ID(P2d) 재키 OPS 런바 — Alembic 리비전 *의도적 유보*(runbook, 스키마 변경 아님)
────────────────────────────────────────────────────────────────────────────
Part 9 P2d 재-ID로 코퍼스 concept_id가 `{TRACK}-{AREA}-{NNN}`(옛 P2a)→`math.<area>.<slug>`로
바뀌었다. 이 로더들은 concept_id를 *opaque str*로 통과시키므로 코드 변경 없이 새 id가 흐르지만,
*이미 옛 id로 적재된 라이브 행*은 재populate 후 orphan으로 남는다(멱등 upsert는 새 id로 신규 행을
넣을 뿐 옛 행을 지우지 않는다). 이 재키는 **스키마 변경이 아니라 데이터/OPS 작업**이며, 라이브
DB 없이 안전히 저작·검증할 수 없어 Alembic 리비전을 유보한다(단일 head 유지). OPS 절차:

  1) 순수 프로젝션 테이블(`concept_node`·`concept_embedding`) — 인바운드 FK가 없다. 옛 id 행을
     `DELETE ... WHERE concept_id ~ '^(ELEM|MID|HIGH|RT|OLY)-'`로 purge한 뒤 로더로 재populate
     (멱등). 안전·기계적이다.
  2) backend `concept` 테이블(UUID PK·`code`=concept_id) — **주의**: UUID PK가 `concept_edge`·
     `concept_standard_link`·L2 mastery·`problem_concept` 등에서 FK로 참조된다. 옛 code 행을
     DELETE하면 그 참조가 cascade/orphan된다. 재populate는 새 code로 *새 UUID 행*을 만들 뿐이라
     옛 UUID 참조를 잇지 못한다. 따라서 code를 옛→새로 *제자리 UPDATE*(UUID 보존·FK 안정)하는
     크로스워크가 필요하다 — `aliases`에 보존된 옛 TRACK-AREA-NNN으로 옛 code를 찾아 새 canonical
     로 UPDATE. 이 remap은 라이브 데이터 형상에 의존하므로 라이브 DB에서 검증 후 리비전화한다.

Alembic 리비전은 위 2)의 remap을 라이브에서 검증한 뒤 별도 슬라이스로 추가한다(현 시점 유보).

────────────────────────────────────────────────────────────────────────────
sync 엔진 (벡터 store 좌석 규약 재사용·신규 seam 0)
────────────────────────────────────────────────────────────────────────────
슬3 `embedding._build_sync_engine`(sync psycopg·지연 import·`db_disable_pool` NullPool 가드)을
*그대로 재사용*한다(슬117 `node_projection`과 동일 — 같은 코드베이스 sync 좌석 규약·CLAUDE.md
신규 금지). 이 적재기는 벡터 컬럼을 만지지 않으나 pgvector 어댑터 등록은 무해(no-op)하다. sync URL은
`Settings.sync_database_url`(env 파생)·자격증명 0 하드코딩.

7계층: L1 데이터 기반의 *런타임 엔티티 적재*. 소비(L2 약개념 추천·L4 결선)는 이 행을 쓰되 여기서
구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — 슬117 node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

# name_ko는 재-ID(P2d)로 노드에서 제거돼 형제 `locales/ko.json`에서 재소싱한다(공유 헬퍼).
from whymath_backend.l1.concept_graph.locale import load_locale_ko
from whymath_backend.schema.enums import ConceptLevel

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# ──────────────────────────────────────────────────────────────────────────
# 유도 상수·매핑
# ──────────────────────────────────────────────────────────────────────────
# graph 403개 노드는 전부 *세부개념*(평면 개념 목록·단원/소단원 위계 아님) → level 고정 유도.
# 'unspecified' enum 추가·nullable화(스키마 변경)를 피하는 교수학적으로 정확한 기본값.
_DEFAULT_LEVEL: ConceptLevel = ConceptLevel.세부개념

# difficulty_tier[0, 24] → intrinsic_difficulty[1.0, 5.0] 선형 스케일(0→1.0·24→5.0).
# Numeric(3,2) 정밀도(소수 2자리)로 반올림(컬럼 정합·재적재 결정론).
_DIFFICULTY_TIER_MAX: int = 24
_DIFFICULTY_MIN: float = 1.0
_DIFFICULTY_MAX: float = 5.0
_DIFFICULTY_DECIMALS: int = 2

# subject 매핑(_SUBJECT_BY_DOMAIN·map_subject)은 제거됐다 — `Concept.subject` 컬럼이 Overlay 분리로
# 사라졌다(rev f3a4b5c6d7e8·math_dsl_remediation_design.md §3). 교육과정 분류는 CurriculumEntry
# (domain_label)가 단일 진실. graph `domain`은 원천 코퍼스에 남아 향후 Overlay 적재로 재구성 가능.


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(transform `_opt`·node_projection 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: object) -> int | None:
    """정수 옵션 파싱 — 빈/None/비정수는 None(transform `_int_opt`·node_projection 미러)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _str_list(value: object) -> list[str]:
    """graph.json `aliases`(list[str]) → 정규화 str 목록. 비-list나 빈 원소는 안전 처리.

    list/tuple이 아니면 빈 목록(옛 graph.json엔 aliases 부재 → 빈 배열로 graceful·NOT NULL 정합).
    각 원소는 strip하고 빈 문자열은 제외한다(data-pipeline `_validate_aliases`가 빈 별칭을
    금지하므로 정상 산출엔 없지만 방어적으로 거른다 — 조용한 빈 별칭 적재 차단).
    """
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def scale_difficulty(difficulty_tier: int | None) -> float | None:
    """difficulty_tier[0, 24] → intrinsic_difficulty[1.0, 5.0] 선형 스케일(None→None).

    0→1.0·12→3.0·24→5.0. tier가 범위를 벗어나도(이론상 schema ge=0 le=24가 막음) clamp해
    Numeric(3,2)·schema ge=1 le=5 제약을 위반하지 않게 한다(방어). 소수 2자리 반올림.
    """
    if difficulty_tier is None:
        return None
    clamped = max(0, min(_DIFFICULTY_TIER_MAX, difficulty_tier))
    scaled = _DIFFICULTY_MIN + (clamped / _DIFFICULTY_TIER_MAX) * (
        _DIFFICULTY_MAX - _DIFFICULTY_MIN
    )
    return round(scaled, _DIFFICULTY_DECIMALS)


# ──────────────────────────────────────────────────────────────────────────
# 적재 레코드 (graph.json → backend Concept 컬럼 값)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class BackendConceptRecord:
    """backend `concept` 행으로 적재할 한 개념의 *런타임 식별* 값 — UC 브리지 키 + 유도 필드.

    `graph.json`의 `Concept.model_dump()`에서 backend 런타임 엔티티에 필요한 최소 식별만 추린
    값이다. **`description`·`formal_definition`·`intuitive_explanation` 슬롯이 *없다*** — graph
    부재·검수 책임 필드라 적재기가 채우지 않으므로 레코드에도 두지 않는다(redaction·구조적 차단).
    `code`가 concept_id(브리지 키·재ID 후 `math.<area>.<slug>`)이고, `source_id`·`aliases`는
    재ID 추적성 직결 필드, 나머지는 backend Concept 컬럼에 직결/유도된다.
    """

    # 브리지 키·직결
    code: str  # = concept_id(재ID 후 'math.<area>.<slug>') — UNIQUE 브리지 키
    name_ko: str  # locales/ko.json(concept_id 조인)에서 재소싱(P2d — 노드 비내장)
    # 재ID 추적성 직결(2026-06-16) — 옛 graph.json엔 부재 → None/빈 배열
    source_id: str | None  # 원천 src_id(파생 추적)
    aliases: list[str]  # [옛 TRACK-AREA-NNN, 옛 UC, src_id](옛 키 join 보존)
    # 유도
    level: ConceptLevel  # 세부개념 고정(NOT NULL 충족)
    intrinsic_difficulty: float | None  # difficulty_tier 스케일
    # cognition 참조(Phase 2b-2) — 이 개념이 exercise하는 스킬 skill_id 목록(정본 노드
    # behavior_skills 직결·2b-1 저작). skill mastery의 concept→skill 브리지·참조 키(본문 아님).
    behavior_skills: list[str]


def load_backend_concepts_from_graph_json(path: Path) -> list[BackendConceptRecord]:
    """슬1 산출 `graph.json` → backend `Concept` 적재 레코드 목록(UC 브리지·redaction 청결).

    `concepts` 배열의 각 항목에서 **`concept_id`·`source_id`·`aliases`** 직결 + name_ko(locale
    조인·아래) + `difficulty_tier`→intrinsic_difficulty를 유도한다(본문 3종·오개념 컬럼은 Phase
    1b로 노드에서 제거·redaction). concept_id는 *형식 불문*
    으로 code에 들어가므로 재-ID 후 canonical 형식(`math.<area>.<slug>`)이 별도 변경 없이 흐른다
    (옛 `{TRACK}-{AREA}-{NNN}`·옛 UC도 동일 경로). source_id/aliases는 옛
    graph.json(부재)이면 None/빈 배열로 graceful. `level`은 `세부개념` 고정(graph 노드는 전부 세부
    개념). **`description`·`formal_definition`은 읽지 않는다**(graph 부재이며, 오염돼 들어와도
    레코드에 슬롯이 없어 차단).

    `name_ko`는 재-ID(P2d)로 노드에서 제거돼 형제 `locales/ko.json`(`{concept_id: name_ko}`)에서
    재소싱한다 — 노드 내장 name_ko가 있으면(옛 graph.json) 우선하고, 없으면 locale에서 조회한다
    (`record.get("name_ko") or locale.get(id)`·옛/새 둘 다 graceful·값 바이트 동일). name_ko가
    빈/None이면(locale 부재·오염) 그 개념은 *건너뛴다*(NOT NULL 위반 방지·조용한 빈 적재 금지).
    `review_status` 무관 전량(403) — 게이팅은 조회 몫.

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: concept_id 없는 항목(슬1 산출은 항상 concept_id를 갖는다 — 방어).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    locale_ko = load_locale_ko(path)
    out: list[BackendConceptRecord] = []
    for record in payload.get("concepts", []):
        concept_id = str(record.get("concept_id", "")).strip()
        if not concept_id:
            raise ValueError(f"graph.json 개념에 concept_id가 없습니다: {record!r}")

        # name_ko: 노드 내장(옛 graph.json) 우선, 없으면 locale 조인(새 graph.json·P2d).
        name_ko = _opt_str(record.get("name_ko")) or locale_ko.get(concept_id)
        if name_ko is None:
            # name_ko 누락(locale 부재·오염 입력) — NOT NULL 위반 대신 건너뛴다(정직).
            continue

        out.append(
            BackendConceptRecord(
                code=concept_id,
                name_ko=name_ko,
                # 재ID 추적성(2026-06-16) — graph.json 직결. 옛 graph.json 부재 시 None/빈 배열.
                source_id=_opt_str(record.get("source_id")),
                aliases=_str_list(record.get("aliases")),
                level=_DEFAULT_LEVEL,
                intrinsic_difficulty=scale_difficulty(_opt_int(record.get("difficulty_tier"))),
                # 정본 노드 behavior_skills 직결(2b-1 저작·부재 시 빈 배열). concept→skill 브리지.
                behavior_skills=_str_list(record.get("behavior_skills")),
            )
        )
    return out


class BackendConceptStore:
    """개념그래프 → backend `concept` 런타임 ORM 적재기 — UC(`code`) 충돌 멱등 upsert(sync).

    슬117 `ConceptNodeStore`의 *런타임 엔티티* 짝이다(같은 sync 좌석·멱등 규약). `upsert`는
    `INSERT ... ON CONFLICT(code) DO UPDATE`로 멱등 적재한다 — 같은 UC 재적재는 기존 행을 갱신하고
    **UUID PK(concept_id)는 보존**한다(ON CONFLICT가 PK를 SET하지 않음 — L2 mastery·problem_concept
    FK 안정성에 결정적). 신규 행만 `gen_random_uuid()` server_default로 UUID 발급. sync 엔진은
    슬3 `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0).

    redaction: INSERT 컬럼에 `description`·`formal_definition`·`intuitive_explanation`이 *없다*
    (레코드에 슬롯이 없어 구조적 차단 — 셋 다 NULL로 남아 검수 대기). ON CONFLICT SET에도 없으므로
    재적재가 검수 작성한 본문을 *덮어쓰지 않는다*(검수 결과 보존).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(슬117 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(self, record: BackendConceptRecord, *, overwrite_cms_edits: bool = False) -> bool:
        """단일 개념을 backend `concept`에 upsert (멱등·`code` 충돌 갱신·UUID PK 보존).

        **CMS 소유 보호(P3-26)**: `cms_edited_at`이 채워진 행(CMS가 만든 개념)은 갱신하지 않고
        False를
        돌려준다(`overwrite_cms_edits=True`면 덮어쓰고 표지를 비운다).

        `INSERT ... ON CONFLICT(code) DO UPDATE` — 런타임 식별 필드(name_ko·source_id·aliases·
        level·intrinsic_difficulty·behavior_skills)를 갱신한다(behavior_skills=concept→skill 참조
        키·Phase 2b-2·skill mastery 브리지·본문 아님). **PK(concept_id)는 SET하지 않아 보존**되고
        (재적재 시 기존 UUID 유지), 신규 행만 server_default로 발급한다. **본문 3종·오개념 컬럼은
        Phase 1b로 제거돼 INSERT/SET에 아예 없다**(redaction·구조적 차단). `level`은 enum 값으로
        바인딩한다(`use_enum_values` 직렬화 등가 — PG enum 컬럼에 한글 값).
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.cms_edit_marker import upsert_guard, upsert_skipped
        from whymath_backend.db.models.concept import Concept

        stmt = pg_insert(Concept).values(
            code=record.code,
            name_ko=record.name_ko,
            source_id=record.source_id,
            aliases=record.aliases,
            level=record.level.value,
            intrinsic_difficulty=record.intrinsic_difficulty,
            behavior_skills=record.behavior_skills,
        )
        # code 충돌 시 갱신 — concept_id(PK)·created_at은 SET하지 않는다(보존·redaction).
        where, release = upsert_guard(Concept, overwrite=overwrite_cms_edits)
        upsert = stmt.on_conflict_do_update(
            index_elements=[Concept.code],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "source_id": stmt.excluded.source_id,
                "aliases": stmt.excluded.aliases,
                "level": stmt.excluded.level,
                "intrinsic_difficulty": stmt.excluded.intrinsic_difficulty,
                "behavior_skills": stmt.excluded.behavior_skills,
                **release,
            },
            where=where,
        ).returning(Concept.concept_id)
        with self._get_engine().begin() as conn:
            return not upsert_skipped(conn.execute(upsert))


def populate_backend_concepts(
    records: Sequence[BackendConceptRecord],
    *,
    settings: Settings | None = None,
    store: BackendConceptStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> int:
    """개념그래프 개념을 backend `concept` 런타임 엔티티로 멱등 upsert 적재. 반환=적재 행 수.

    슬117 `populate_concept_nodes`의 *런타임 엔티티* 짝이다 — 각 레코드를 UC(`code`) 키로 upsert한다
    (403 전량·review_status 포함). 멱등(재실행 시 갱신·UUID 보존). store 미주입 시 슬3 sync 엔진
    재사용 `BackendConceptStore`를 만든다.

    **CMS 소유 보호(P3-26)**: CMS가 만든 개념과 코드가 같은 레코드는 건너뛰고 `conflicts`에
    `concept:<code>`로 보고한다 — 반환 행 수에는 포함하지 않는다.
    """
    from whymath_backend.db.cms_edit_marker import format_conflict

    resolved = settings if settings is not None else get_settings()
    concept_store = store if store is not None else BackendConceptStore(settings=resolved)
    written = 0
    for record in records:
        if concept_store.upsert(record, overwrite_cms_edits=overwrite_cms_edits):
            written += 1
        elif conflicts is not None:
            conflicts.append(format_conflict("concept", record.code))
    return written


__all__ = [
    "BackendConceptRecord",
    "BackendConceptStore",
    "load_backend_concepts_from_graph_json",
    "populate_backend_concepts",
    "scale_difficulty",
]
