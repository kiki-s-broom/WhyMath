"""개념그래프 graph.json → backend `curriculum_entry`(KR 셀) 멱등 적재기 (L1·Overlay).

`l1/concept_graph/backend_concept.py`(개념 노드 적재)의 *교육과정 Overlay* 짝이다. `Concept`에서
제거된 교육과정 필드(`subject`·`curriculum_version`·`grade_introduced`·`semester_introduced`·rev
`d1e2f3a4b5c6`·`f3a4b5c6d7e8`)를 대신해 교육과정 분류를 담는 단일 진실이 `curriculum_entry`
Overlay다(math_dsl_risk_register Q5·Q8·Q10-③ "노드는 의미만·교육과정은 Overlay"). 이 모듈이 그
Overlay의 *적재기*를 놓는다 — 개념그래프의 한국(KR) 교육과정 신호를 (concept_id × "KR") 셀로
멱등 적재한다.

────────────────────────────────────────────────────────────────────────────
KR 셀 소스 (graph.json 개념 중심·직접 — 2026-06-30 결정)
────────────────────────────────────────────────────────────────────────────
CurriculumEntry는 (concept_id × country_code) 셀이라 *concept_id로 키잉*된다. graph.json 개념은
이미 concept_id에 KR 교육과정 신호(`domain`·`grade_band_hint`·`standard_codes`)를 묶어 두므로,
개념당 1개의 KR 셀로 직접 매핑한다(backend_concept와 동일 소스·concept_id 정합). standards.json은
norm_id 중심이라 셀(concept 중심)과 키가 어긋나 조인이 필요한데, Phase 1은 graph.json 직접 매핑을
택한다. Phase 1 범위는 **KR만**(US는 ccss_code뿐 표준 코퍼스 없음·IMO는 코퍼스 없음).

graph.json 개념 키 → CurriculumEntry 필드 매핑:
  - `concept_id`            → `concept_id`(복합키)·`entry_id`(=`{concept_id}:KR`·결정적·멱등키)

entry_id 규약 (과목 확장 S1 — subject_expansion_readiness.md §9):
  셀 의미키는 (concept_id, country_code, subject) 3-튜플이고 이 로더는 KR **수학** 셀만
  적재한다(`subject=_KR_SUBJECT`). 수학 셀 entry_id는 기존 `{concept_id}:KR` 형식 **불변**
  (무접미 — 데이터 churn 0), 비수학 셀만 `:{subject}` 접미를 붙인다(미래 규약 — 물리 첫 적재
  슬라이스 소관·이 로더는 수학만 적재하므로 생성 로직 현행 유지). ⚠️ 이 `subject`(교과:
  '수학')는 NCIC `AchievementStandard.subject`(과목: '공통수학1')와 granularity가 다르다
  (schema docstring 교차 명기).
  - `domain`               → `domain_label`(그 나라 교육과정 영역명)
  - `grade_band_hint`      → `grade_band`(학년대 라벨 직결) + `introduced_grade`(밴드 하한=최초
    도입 학년·KR 1~12 번호·_GRADE_BAND_TO_INTRODUCED_GRADE)
  - `standard_codes`       → `national_standard_codes`(NCIC 성취기준 코드 느슨참조)
  - `prerequisite_concept_ids` → `prerequisite_concept_ids`(그 나라 교육과정 내 선수개념)
  - `review_status`        → `confidence`(reviewed→0.9·그 외→0.6·데이터 품질 신뢰도)

KR 상수(graph.json `source_citation`에서 정직 도출 — 교육부 고시 제2022-33호·NCIC·공공누리 1유형):
  country_code="KR" · license_id=KR-NCIC · curriculum_revision="2022 개정" · is_present=True ·
  source_name/source_code/source_url은 _KR_* 상수. is_present=True라 source_url이 비면 schema
  validator가 막으므로 NCIC 포털 URL을 상수로 채운다(존재 주장의 근거 출처).

`required_depth`(휴리스틱·사용자 결정 2026-07): 코퍼스에 인지 깊이 주석이 없어(cognitive_level
  원문 부재) `grade_band` 학년진행을 깊이 프록시로 파생한다(`_GRADE_BAND_TO_REQUIRED_DEPTH` —
  나선형 교육과정 통설 기반 coarse 휴리스틱·개념별 진리 아님). L6 깊이정렬 *랭킹 보너스*에만 쓰이고
  (하드 게이트 아님), cognitive_level 원문 주석이 확보되면 대체한다. 미지 밴드는 None(정직 폴백).

미매핑(소스에 신호 없음·날조 금지 — CLAUDE.md "교수학 내용 날조 금지"):
  `cognitive_level`·`is_assessed`·
  `assessment_format`·`notation_local`·`terminology_local`·`notation_variants`·
  `followup_concept_ids`·`sub_domain_label`·`textbook_unit_refs`·`introduced_context`·
  `effective_from`·`source_document`·`verified_by`.

────────────────────────────────────────────────────────────────────────────
원자 축 이관 (S2-07 — 크로스워크 전파로 L6 깊이정렬 신호 복원)
────────────────────────────────────────────────────────────────────────────
S2-03이 `problem_concept`를 원자 백본 행(Concept.code=원자코드)으로 재연결하면서, gating의 깊이
주입 체인(`api/gating.py` `_fetch_problem_concept_codes` → `CurriculumDepthResolver`)이 모으는
concept code가 *원자 코드 공간*으로 바뀌었다 — canonical(`math.*`)만 키잉된 curriculum_entry와
조인이 미스나 required_depth가 전부 None(깊이 랭킹 보너스 0 폴백·신호 소실)이었다.

`derive_atom_curriculum_entries`가 이 미스매치를 데이터 측에서 복원한다: canonical KR 셀 ×
크로스워크(canonical concept_id → atom_codes)를 조인해 **원자 코드로 키잉된** KR 셀을 유도한다.
런타임 reader(`CurriculumDepthResolver` — 유일 소비처)는 무변경이다 — reader가 크로스워크
코퍼스를 런타임에 읽게 하는 (b)안은 "런타임 코퍼스 reader 0" 원칙(코퍼스는 적재기만 읽고
런타임은 DB만 본다)에 반해 기각, 적재 시점 유도((a)안)를 택했다.

전파 규칙(스킬 전파 `derive_atom_behavior_skills` 선례):
  - 매핑된 concept의 **atom_codes 전체**에 depth를 전파한다(primary만 아님) — required_depth는
    grade_band 프록시의 *방송형* 속성이라 개념의 전 원자가 같은 학년 밴드에 속한다.
    primary_atom_code는 mastery *배타 귀속* 전용이라 방송형 깊이 전파에는 부적합하다.
  - 충돌(복수 canonical → 같은 원자): required_depth가 *가장 깊은* 원천 셀이 이긴다
    (RequiredDepth 위계 — api/gating.py `_DEPTH_ORDER`와 동일 서열·아래 `_REQUIRED_DEPTH_RANK`).
    동순위 tie-break는 원천 concept_id 사전순(결정론). 산출은 entry_id 정렬 — 2회 유도 동일.
  - 크로스워크 미매핑 canonical(atom_codes 빈)·canonical 셀 없는 크로스워크 concept은 원자 행
    0(날조 금지). canonical 셀은 그대로 존치된다(원자 행은 *추가* 축).

────────────────────────────────────────────────────────────────────────────
멱등 (PG ON CONFLICT — backend_concept·standard_loader 규약)
────────────────────────────────────────────────────────────────────────────
`entry_id`(PK·`{concept_id}:KR`)는 (concept_id, country_code)와 1:1이라 `INSERT ... ON
CONFLICT(entry_id) DO UPDATE`로 멱등 적재한다 — 재적재는 나머지 컬럼을 갱신하되 **`created_at`은
SET하지 않아 보존**(최초 생성 시각 유지)하고 `updated_at`은 갱신한다. 입력 내 entry_id 중복은
*마지막 우선* dedup한다(단일 배치 ON CONFLICT 중복행 오류 방지·standard_loader 선례).

sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0 — backend_concept·standard_loader와
동일 좌석). 자격은 env(`Settings.sync_database_url`)·하드코딩 0. 적재 값은 검증된 schema
`CurriculumEntry`(불변식 게이트)의 `model_dump()`에서 뽑아 바인딩한다(schema가 형식·불변식 게이트,
upsert가 멱등).

법적 메모(공공누리 1유형): 이 Overlay는 교육과정의 *구조·코드*(영역명·학년대·성취기준 코드)만 담고
해설 *본문*은 담지 않는다(schema 법적 메모). NCIC 출처는 공공누리 1유형(상업·가공 OK·출처 표시
필수)이라 구조 메타 보유가 허용된다(licensing_safety.md 가이드 v2.0). 출처 표시는 셀 source_* 필드.

7계층: L1 데이터 기반의 *Overlay 적재*. 소비(자동 커리큘럼 정렬·L6)는 이 셀을 *조회*하되 여기서
구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from whymath_backend.config import Settings, get_settings

# 크로스워크 로더 재사용(S2-07 원자 축 유도 — 신규 파서 0·transfer.py와 동일 코퍼스 계약).
from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    CrosswalkRecord,
    load_crosswalk_records,
)

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — backend_concept·standard_loader와 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.curriculum_entry import CurriculumEntry
from whymath_backend.schema.enums import CurriculumLicense, RequiredDepth

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# ──────────────────────────────────────────────────────────────────────────
# KR 상수 (graph.json source_citation에서 정직 도출 — 교육부 고시 제2022-33호·NCIC·공공누리 1유형)
# ──────────────────────────────────────────────────────────────────────────
_KR_COUNTRY: str = "KR"
# 교과 레벨 subject 축(S1) — 이 로더는 수학 셀만 적재한다(비수학 셀은 미래 슬라이스 소관).
# NCIC AchievementStandard.subject(과목 레벨 '공통수학1')와 granularity 다름(모듈 docstring).
_KR_SUBJECT: Final[str] = "수학"
_KR_LICENSE: CurriculumLicense = CurriculumLicense.KR_NCIC
_KR_SOURCE_NAME: str = "2022 개정 교육과정 — 수학과 교육과정"
_KR_SOURCE_CODE: str = "교육부 고시 제2022-33호 [수학과 교육과정]"
# is_present=True 셀의 근거 출처 URL(schema validator 충족). NCIC 국가교육과정정보센터 포털.
_KR_SOURCE_URL: str = "https://www.ncic.go.kr"
_KR_CURRICULUM_REVISION: str = "2022 개정"
# CUR-10: KR 교육과정의 기본 프레임워크 식별자. curriculum_framework 백필과 동일 값.
_KR_FRAMEWORK_ID: str = "KR_NC_2022"

# review_status → confidence(데이터 품질 신뢰도). reviewed는 검수 완료라 높게, 그 외는 보수적으로.
_CONFIDENCE_REVIEWED: float = 0.9
_CONFIDENCE_DEFAULT: float = 0.6

# grade_band_hint(학년대 밴드) → introduced_grade(밴드 하한=최초 도입 학년·KR 1~12 번호).
# 밴드는 학년 범위라 "처음 도입되는 학년"(schema 정의)은 하한이다(날조 아닌 하한 도출). 미지 밴드는
# None(정직 — 매핑에 없는 라벨은 추정하지 않음).
_GRADE_BAND_TO_INTRODUCED_GRADE: dict[str, int] = {
    "초등학교 1~2학년군": 1,
    "초등학교 3~4학년군": 3,
    "초등학교 5~6학년군": 5,
    "중학교 1~3학년군": 7,  # 중1 = KR 1~12 번호 7
    "고등학교": 10,  # 고1 = KR 1~12 번호 10
}

# grade_band_hint(학년대 밴드) → required_depth(교육과정 요구 깊이) *휴리스틱*(사용자 결정
# 2026-07·"grade_band 학년진행"). graph.json에 인지 깊이(성취기준 동사·cognitive_level) 주석이
# 없어(날조 금지) 학년 진행을 깊이 프록시로 쓴다 — 나선형 교육과정에서 저학년은 인식·기능,
# 고학년으로 갈수록 개념·숙달로 심화한다는 통설에 근거한 *coarse 휴리스틱*이다(개념별 진리 아님).
# L6는 이 깊이를 *목표 난이도*로 환산(awareness 1.5 … mastery 4.5)해 문항 난이도 정합 *랭킹
# 보너스*(하드 게이트 아님·상한 1.5)로만 쓴다 → 매핑이 다소 어긋나도 안전 범위. 인지수준 원문
# 주석이 확보되면 이 휴리스틱을 대체한다(cognitive_level 적재 별 슬라이스). 미지 밴드는 None(정직).
_GRADE_BAND_TO_REQUIRED_DEPTH: dict[str, RequiredDepth] = {
    "초등학교 1~2학년군": RequiredDepth.awareness,  # 수 세기 등 도입·인식
    "초등학교 3~4학년군": RequiredDepth.procedural,  # 연산 기능 습득
    "초등학교 5~6학년군": RequiredDepth.procedural,
    "중학교 1~3학년군": RequiredDepth.conceptual,  # 개념 이해·형식화
    "고등학교": RequiredDepth.mastery,  # 심화·증명·전이(수능 숙달 요구)
}


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(backend_concept `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _str_list(value: object) -> list[str]:
    """graph.json 배열(list[str]) → 정규화 str 목록. 비-list·빈 원소 안전 처리(backend_concept).

    list/tuple이 아니면 빈 목록, 각 원소는 strip하고 빈 문자열은 제외한다(빈 원소 적재 차단).
    """
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _confidence_for(review_status: object) -> float:
    """review_status → confidence. 'reviewed'면 0.9, 그 외(pending 등·None)면 0.6(보수적)."""
    return _CONFIDENCE_REVIEWED if _opt_str(review_status) == "reviewed" else _CONFIDENCE_DEFAULT


def _kr_entry_from_concept(concept: dict[str, Any], *, now: datetime) -> CurriculumEntry | None:
    """graph.json 개념 1개 → 검증된 KR `CurriculumEntry` 셀(없으면 None).

    `concept_id`가 비면 셀을 만들 수 없어 None을 반환한다(조용한 빈 적재 금지·NOT NULL 정합).
    나머지 신호는 모듈 docstring 매핑대로 추출하고, KR 상수·`now`를 채워 schema로 검증한다
    (schema가 형식·불변식 게이트 — is_present=True인데 source_url 비면 ValidationError 등).
    """
    concept_id = _opt_str(concept.get("concept_id"))
    if concept_id is None:
        return None

    grade_band = _opt_str(concept.get("grade_band_hint"))
    introduced_grade = (
        _GRADE_BAND_TO_INTRODUCED_GRADE.get(grade_band) if grade_band is not None else None
    )
    # required_depth 휴리스틱 — grade_band 학년진행에서 파생(_GRADE_BAND_TO_REQUIRED_DEPTH).
    # 미지·미제공 밴드는 None(정직 폴백 — L6 깊이보너스 0·기존 동작 불변).
    required_depth = (
        _GRADE_BAND_TO_REQUIRED_DEPTH.get(grade_band) if grade_band is not None else None
    )

    return CurriculumEntry(
        # 식별 — 복합키 (concept_id, "KR", "수학") + 결정적 표면키 entry_id(멱등키).
        # 수학 셀 entry_id는 무접미 불변(S1 규약 — 모듈 docstring "entry_id 규약").
        concept_id=concept_id,
        country_code=_KR_COUNTRY,
        subject=_KR_SUBJECT,
        entry_id=f"{concept_id}:{_KR_COUNTRY}",
        # 출처 — KR 상수(graph.json source_citation 도출)
        source_name=_KR_SOURCE_NAME,
        source_code=_KR_SOURCE_CODE,
        source_url=_KR_SOURCE_URL,
        license_id=_KR_LICENSE,
        # 시점
        introduced_grade=introduced_grade,
        grade_band=grade_band,
        curriculum_revision=_KR_CURRICULUM_REVISION,
        framework_id=_KR_FRAMEWORK_ID,
        # 맥락
        domain_label=_opt_str(concept.get("domain")),
        # 깊이 — grade_band 학년진행 휴리스틱(cognitive_level 원문 주석 확보 시 대체)
        required_depth=required_depth,
        # 매핑·위계 — graph.json 직결(NCIC 코드·그 나라 선수개념)
        national_standard_codes=_str_list(concept.get("standard_codes")),
        prerequisite_concept_ids=_str_list(concept.get("prerequisite_concept_ids")),
        # 상태 — KR 교육과정 개념이므로 present, 신뢰도는 review_status 파생
        is_present=True,
        confidence=_confidence_for(concept.get("review_status")),
        created_at=now,
        updated_at=now,
    )


def load_kr_curriculum_entries_from_graph_json(
    path: Path, *, now: datetime | None = None
) -> list[CurriculumEntry]:
    """슬1 산출 `graph.json` → backend `curriculum_entry` KR 셀 목록(개념당 1셀·hermetic).

    `concepts` 배열의 각 개념을 KR 셀로 매핑한다(`_kr_entry_from_concept`). `concept_id`가 빈 개념은
    건너뛴다(조용한 빈 적재 금지). `now`는 created_at·updated_at에 쓰며, 미지정 시 UTC 현재 시각을
    쓴다(테스트는 결정성을 위해 주입). PG 불요(순수 빌더 — 적재는 `CurriculumEntryStore.populate`).

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[CurriculumEntry] = []
    for concept in payload.get("concepts", []):
        entry = _kr_entry_from_concept(concept, now=resolved_now)
        if entry is not None:
            out.append(entry)
    return out


# RequiredDepth 위계(얕음→깊음) 서수 — api/gating.py `_DEPTH_ORDER`와 동일 서열(문항 주입 시
# "가장 깊은 깊이" 선택과 같은 위계). 키는 enum *값* 문자열이다 — CurriculumEntry가
# use_enum_values=True라 검증된 셀의 required_depth는 문자열로 저장되기 때문(schema 컨벤션).
_REQUIRED_DEPTH_RANK: dict[str, int] = {
    RequiredDepth.awareness.value: 0,
    RequiredDepth.procedural.value: 1,
    RequiredDepth.conceptual.value: 2,
    RequiredDepth.mastery.value: 3,
}


def _depth_rank(entry: CurriculumEntry) -> int:
    """셀의 required_depth 위계 서수. None(깊이 미상)은 -1 — 어떤 명시 깊이보다 얕게 취급.

    충돌 시 "깊이 신호가 있는" 셀이 "없는" 셀을 이기게 한다(신호 보존 — 미상 셀이 명시 깊이를
    덮어쓰면 L6 깊이정렬 신호가 다시 소실된다).
    """
    depth = entry.required_depth
    if depth is None:
        return -1
    # use_enum_values=True라 보통 str이지만, 방어적으로 enum 인스턴스도 값으로 정규화한다.
    value = depth.value if isinstance(depth, RequiredDepth) else str(depth)
    return _REQUIRED_DEPTH_RANK[value]


def derive_atom_curriculum_entries(
    canonical_entries: Sequence[CurriculumEntry],
    crosswalk_records: Sequence[CrosswalkRecord],
) -> list[CurriculumEntry]:
    """canonical KR 셀 × 크로스워크 조인 → **원자 코드로 키잉된** KR 셀 유도(순수·PG 불요).

    S2-07 원자 축 이관 본체(모듈 docstring §원자 축 이관). 크로스워크의 각 매핑 행에 대해 원천
    canonical 셀의 신호를 `atom_codes` **전체**에 전파한다 — required_depth는 grade_band 프록시의
    방송형 속성이라 개념의 전 원자가 같은 학년 밴드다(primary-only는 mastery 배타 귀속 전용이라
    부적합 — `derive_atom_behavior_skills` 전파 선례). 원자별 유도 셀은 `concept_id=원자코드`·
    `entry_id="{원자코드}:{country_code}"`(S1 수학 셀 무접미 규약)이고 나머지 필드(required_depth·
    is_present·source_url·confidence·country_code·subject 등)는 원천 셀을 승계한다 — schema
    불변식(is_present=True → source_url 필수)은 원천 셀이 이미 통과했으므로 승계로 보존되고,
    재검증(CurriculumEntry 생성자)으로 한 번 더 게이트한다.

    충돌(복수 canonical → 같은 원자): required_depth가 *가장 깊은* 원천 셀 승계(`_depth_rank`
    위계·None은 최저), 동순위는 원천 concept_id 사전순으로 앞선 쪽(결정론). 산출은 entry_id
    정렬이라 같은 입력에 2회 유도해도 동일하다.

    크로스워크 미매핑(atom_codes 빈)·canonical 셀 없는 크로스워크 concept은 원자 행 0(날조 금지).
    canonical 셀 목록 자체는 변경하지 않는다(원자 행은 *추가* 축 — 호출자가 둘을 합쳐 적재).
    """
    canonical_by_id: dict[str, CurriculumEntry] = {e.concept_id: e for e in canonical_entries}

    # 원자코드 → 승자 원천 셀. 결정론을 위해 크로스워크를 concept_id 사전순으로 순회한다 —
    # 동순위 충돌에서 "사전순 앞선 원천"이 항상 이기도록(먼저 앉은 쪽 유지 + 더 깊은 쪽만 교체).
    winner_by_atom: dict[str, CurriculumEntry] = {}
    for record in sorted(crosswalk_records, key=lambda r: r.concept_id):
        if not record.atom_codes:  # 미매핑 — 강제 귀속 금지(원자 행 0)
            continue
        source = canonical_by_id.get(record.concept_id)
        if source is None:  # canonical 셀 없는 크로스워크 concept — 원자 행 0(날조 금지)
            continue
        for atom_code in record.atom_codes:
            incumbent = winner_by_atom.get(atom_code)
            # 최심 승계: 더 깊은 쪽만 교체(동순위는 사전순 선점 유지 → concept_id 사전순 tie-break).
            if incumbent is None or _depth_rank(source) > _depth_rank(incumbent):
                winner_by_atom[atom_code] = source

    out: list[CurriculumEntry] = []
    for atom_code in sorted(winner_by_atom):  # entry_id(=원자코드 접두) 정렬 — 결정론 산출
        source = winner_by_atom[atom_code]
        payload = source.model_dump()
        payload["concept_id"] = atom_code
        # S1 entry_id 규약 승계 — 수학 셀 무접미 `{concept_id}:{country_code}`.
        payload["entry_id"] = f"{atom_code}:{source.country_code}"
        # 생성자 재검증 — 승계 필드가 schema 불변식(is_present→source_url 등)을 만족함을 게이트.
        out.append(CurriculumEntry(**payload))
    return out


def load_kr_curriculum_entries_with_atoms(
    graph_path: Path,
    crosswalk_path: Path,
    *,
    now: datetime | None = None,
) -> tuple[list[CurriculumEntry], list[CurriculumEntry]]:
    """graph.json + crosswalk.jsonl → (canonical KR 셀, 유도 원자 KR 셀) 조립(순수·PG 불요).

    기존 `load_kr_curriculum_entries_from_graph_json`(canonical 유도·무변경 유지)과
    `derive_atom_curriculum_entries`(원자 축 유도)를 결합한다. 반환 두 목록을 합쳐 적재하면
    canonical 축(개념 그래프 소비처)과 원자 축(S2-03 이후 gating 깊이 조인) 양쪽이 hit한다.

    ⚠️ 이 경로는 **대학 원자를 낳지 않는다**(아래 "대학 원자 직접 유도" 절 참조) — canonical
    개념그래프(graph.json, 437개념)에 대학 개념이 0건이고 크로스워크도 대학 원자를 0건 매핑하기
    때문이다. 대학 축은 `load_kr_curriculum_entries_for_university_atoms`가 별도로 담당한다.

    Raises:
        FileNotFoundError: graph.json 또는 crosswalk.jsonl 부재.
        ValueError: 크로스워크 코퍼스 계약 위반(concept_id 누락/중복 — `load_crosswalk_records`).
    """
    canonical = load_kr_curriculum_entries_from_graph_json(graph_path, now=now)
    crosswalk = load_crosswalk_records(crosswalk_path)
    atoms = derive_atom_curriculum_entries(canonical, crosswalk)
    return canonical, atoms


# ──────────────────────────────────────────────────────────────────────────
# 대학 원자 직접 유도 (W0 — S-1: 커리큘럼 오버레이에 대학 밴드 부재 해소)
# ──────────────────────────────────────────────────────────────────────────
# 실측(2026-08-05): canonical 개념그래프(`concept_graph_v1/graph.json`, 437개념)의
# `grade_band_hint`는 "고등학교"까지만 존재하고(대학 0건), 대학원자 유도의 유일한 경로인
# `concept_atom_crosswalk_v1/crosswalk.jsonl`(437레코드·canonical 1:1)도 대학 원자(atom_graph_v1
# school_level="대학" 1,069건)를 단 하나도 매핑하지 않는다. 즉
# `load_kr_curriculum_entries_with_atoms`(canonical → 크로스워크 유도) 경로로는 대학 원자에
# required_depth·introduced_grade 신호가
# 원리상 영원히 도달하지 않는다 — 두 dict에 "대학" 키를 추가하는 것만으로는 아무 원자도
# 매핑되지 않아 눈속임이 된다(날조 회피). 이 절은 atom_graph_v1의 대학 원자를 *직접* 읽어
# 원자코드로 키잉된 KR 셀을 유도한다 — canonical을 우회하는 게 아니라, 대학 축이 애초에
# canonical 그래프 밖의 자산이므로 정공법이다.

# atom_graph_v1의 `grade_band`("1학년".."4학년")는 전체 2,683 원자 중 대학 원자(1,069건)에만
# 나타나는 값이다(초·중·고 밴드는 "N~M학년군"·"고N" 표기라 겹치지 않음 — 2026-08-05 corpus
# 실측: 이 4개 라벨의 전체 등장 횟수와 대학 필터 등장 횟수가 정확히 일치).
_UNIV_GRADE_TO_INTRODUCED_GRADE: dict[str, int] = {
    # KR 1~12(초1=1…고3=12, `_GRADE_BAND_TO_INTRODUCED_GRADE`) 다음 번호를 그대로 이어 붙인
    # 로더 내부 관례다(제도가 정한 학년 번호가 아니다) — `introduced_grade`의 "국가 내 학년
    # 정수" 계약을 지키면서 대학 1~4학년을 고등학교 뒤에 정렬하기 위함(정렬용 확장, 교육학적
    # 주장 아님).
    "1학년": 13,
    "2학년": 14,
    "3학년": 15,
    "4학년": 16,
}

# RequiredDepth는 awareness~mastery 4단계뿐이라 고등학교가 이미 최심 단계(mastery)다 — 대학은
# 이 4단계 안에서는 더 깊은 값이 없으므로 동일 천장을 유지한다("심화·증명·전이" 서술은 대학
# 정규과정에도 그대로 부합 — 2026-08-05 학년축 최단경로 계획 §3 W0 결정). None으로 두면 L6
# 깊이 랭킹 보너스가 대학 원자에서 항상 0으로 죽으므로(신호 소실) 명시값을 준다.
_UNIV_REQUIRED_DEPTH: RequiredDepth = RequiredDepth.mastery


def _kr_entry_from_university_atom(
    atom: dict[str, Any], *, now: datetime
) -> CurriculumEntry | None:
    """atom_graph_v1 대학 원자 1개 → 원자코드로 키잉된 KR `CurriculumEntry` 셀(없으면 None).

    `_kr_entry_from_concept`(canonical 개념용)의 대학 원자 직결 짝이다 — 필드명이 다르다
    (`concept_id`가 아닌 `code`, `grade_band_hint`가 아닌 `grade_band`, `domain`이 아닌
    `subject_area` — atom_graph_v1 코퍼스 계약, 모듈 상단 키 매핑 표와는 별개).

    `grade_band`가 `_UNIV_GRADE_TO_INTRODUCED_GRADE`에 없는 원자(단원·소단원 헤더 등
    `level != "세부개념"`이라 grade_band가 아예 None인 원자 다수 포함)는 None을 반환해
    건너뛴다 — 신호 없는 원자에 값을 지어내지 않는다(날조 금지).
    """
    atom_code = _opt_str(atom.get("code"))
    if atom_code is None:
        return None
    grade_band = _opt_str(atom.get("grade_band"))
    if grade_band is None or grade_band not in _UNIV_GRADE_TO_INTRODUCED_GRADE:
        return None

    return CurriculumEntry(
        concept_id=atom_code,
        country_code=_KR_COUNTRY,
        subject=_KR_SUBJECT,
        entry_id=f"{atom_code}:{_KR_COUNTRY}",
        source_name=_KR_SOURCE_NAME,
        source_code=_KR_SOURCE_CODE,
        source_url=_KR_SOURCE_URL,
        license_id=_KR_LICENSE,
        introduced_grade=_UNIV_GRADE_TO_INTRODUCED_GRADE[grade_band],
        grade_band=grade_band,
        curriculum_revision=_KR_CURRICULUM_REVISION,
        domain_label=_opt_str(atom.get("subject_area")),
        required_depth=_UNIV_REQUIRED_DEPTH,
        national_standard_codes=_str_list(atom.get("standard_codes")),
        # 원자 노드에 선수개념 필드가 없다(선수관계는 별도 edges 배열) — 조인 없이 지어내지
        # 않는다(날조 금지). 필요해지면 edges 조인은 후속 슬라이스.
        prerequisite_concept_ids=[],
        is_present=True,
        # 원자 코퍼스는 canonical의 review_status 신호가 없다(다른 계약) — 보수적 기본값 고정.
        confidence=_CONFIDENCE_DEFAULT,
        created_at=now,
        updated_at=now,
    )


def load_kr_curriculum_entries_for_university_atoms(
    atom_graph_path: Path, *, now: datetime | None = None
) -> list[CurriculumEntry]:
    """atom_graph_v1 대학 원자 → 원자코드로 키잉된 KR 셀 목록(순수·PG 불요·entry_id 정렬).

    ⚠️ `atom_graph_path`는 `load_kr_curriculum_entries_with_atoms`의 `graph_path`
    (canonical 개념그래프의 graph.json)와 **다른 파일**이다 — 이 함수는 원자 그래프의
    graph.json(대학 원자 포함)을 읽는다. `load_kr_curriculum_entries_with_atoms`의
    대학 보충 경로다: 크로스워크가 대학 원자를 0건 매핑하므로 이 함수가 없으면 대학 원자
    1,069건은 커리큘럼 오버레이에 영원히 나타나지 않는다(모듈 docstring "대학 원자 직접 유도"
    절 참조). 호출자가 이 목록을 canonical·원자(K-12) 목록과 합쳐 적재한다 — entry_id 충돌
    없음(원자코드 공간이 K-12·대학 사이에서 겹치지 않음).

    Raises:
        FileNotFoundError: atom_graph.json 부재.
    """
    resolved_now = now if now is not None else datetime.now(timezone.utc)
    payload = json.loads(atom_graph_path.read_text(encoding="utf-8"))
    out: list[CurriculumEntry] = []
    for atom in payload.get("concepts", []):
        if atom.get("school_level") != "대학":
            continue
        entry = _kr_entry_from_university_atom(atom, now=resolved_now)
        if entry is not None:
            out.append(entry)
    out.sort(key=lambda e: e.entry_id)  # 결정론 산출(canonical 로더와 동일 관례)
    return out


class CurriculumEntryStore:
    """개념그래프 → backend `curriculum_entry` 적재기 — entry_id PK 충돌 멱등 upsert(sync).

    `BackendConceptStore`(개념 노드)·`AchievementStandardStore`(성취기준)의 *Overlay* 짝이다(같은
    sync 좌석·멱등 규약). `populate`는 각 셀을 `INSERT ... ON CONFLICT(entry_id) DO UPDATE`로 멱등
    적재한다 — 같은 entry_id 재적재는 나머지 컬럼을 갱신하되 **`created_at`은 SET 안 함·보존**하고
    `updated_at`은 갱신한다(최초 생성 시각 유지). 입력 내 entry_id 중복은 적재 전 *마지막 우선*
    dedup한다(단일 배치 ON CONFLICT 중복행 오류 방지). sync 엔진은 슬3 `_build_sync_engine`을
    재사용해 지연 생성·캐시한다(신규 seam 0).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(backend_concept 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def populate(self, entries: Sequence[CurriculumEntry]) -> int:
        """KR 셀 schema 모델들을 `curriculum_entry`에 멱등 upsert. 반환=적재 행 수(dedup 후).

        ① entry_id PK 기준 *마지막 우선* dedup(단일 배치 ON CONFLICT 중복행 오류 방지) → ② 각 행을
        `ON CONFLICT(entry_id) DO UPDATE`로 적재(나머지 컬럼 갱신·`entry_id`·`created_at`은 SET 안
        함·보존). 입력 빈 0. 컬럼 값은 검증된 schema `model_dump()`에서 ORM 컬럼키만 추려 바인딩.
        """
        if not entries:
            return 0

        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.models.curriculum_entry import (
            CurriculumEntry as CurriculumEntryORM,
        )

        # entry_id PK 기준 dedup(마지막 우선) — 단일 배치 INSERT의 ON CONFLICT 중복행 오류 방지.
        by_entry_id: dict[str, CurriculumEntry] = {e.entry_id: e for e in entries}
        deduped = list(by_entry_id.values())

        # 갱신 컬럼 집합(ON CONFLICT DO UPDATE SET) — PK·created_at 제외(보존). mapper 컬럼키 도출.
        all_keys = {col.key for col in sa.inspect(CurriculumEntryORM).mapper.column_attrs}
        update_keys = all_keys - {"entry_id", "created_at"}

        with self._get_engine().begin() as conn:
            for entry in deduped:
                payload = entry.model_dump()
                values = {k: v for k, v in payload.items() if k in all_keys}
                stmt = pg_insert(CurriculumEntryORM).values(**values)
                # entry_id(PK) 충돌 시 나머지 갱신 — entry_id·created_at은 SET 안 함(보존·멱등).
                stmt = stmt.on_conflict_do_update(
                    index_elements=[CurriculumEntryORM.entry_id],
                    set_={key: stmt.excluded[key] for key in update_keys},
                )
                conn.execute(stmt)
        return len(deduped)


def populate_kr_curriculum_entries(
    entries: Sequence[CurriculumEntry],
    *,
    settings: Settings | None = None,
    store: CurriculumEntryStore | None = None,
) -> int:
    """KR 커리큘럼 셀을 backend `curriculum_entry`에 멱등 upsert 적재. 반환=적재 행 수.

    `populate_backend_concepts`(개념 노드)의 *Overlay* 짝이다 — `store.populate`로 위임한다(dedup·ON
    CONFLICT는 store 책임). store 미주입 시 슬3 sync 엔진 재사용 `CurriculumEntryStore`를 만든다.
    """
    resolved = settings if settings is not None else get_settings()
    entry_store = store if store is not None else CurriculumEntryStore(settings=resolved)
    return entry_store.populate(entries)


__all__ = [
    "CurriculumEntryStore",
    "derive_atom_curriculum_entries",
    "load_kr_curriculum_entries_for_university_atoms",
    "load_kr_curriculum_entries_from_graph_json",
    "load_kr_curriculum_entries_with_atoms",
    "populate_kr_curriculum_entries",
]
