"""핵심 엔티티 19종 동결 — 정본 `docs/architecture/canonical_entity_model_v1.md`의 기계 집행.

이 파일이 **강제하는 것**(정본화≠집행 — CLAUDE.md):
  ① 81테이블 전수 귀속 — 새 테이블이 생기면 RED. 9월 스키마에 노드가 조용히 불어나는 것을 막는다.
  ② 좌석 실재 — 19종의 좌석 테이블이 사라지거나 개명되면 RED.
  ③ 좌석 부재 4종 — Subject·Hint·AssessmentResult·ContentVersion용 테이블이 생기면 RED.
  ④ 문서 정합 — 정본 문서가 81테이블을 전부 적지 않으면 RED(문서 드리프트 차단).

이 파일이 **강제하지 않는 것**(있는 척 금지):
  · 컬럼 수준 스키마(어떤 필드를 갖는지)는 각 모델의 기존 ORM 테스트 소관이다.
  · "이 테이블이 *올바른* 엔티티에 배정됐는가"는 사람 판단이다 — 기계는 배정의 *전수성*만 본다.
  · 코드 밖 저작 스키마(`schemas/v1.1/*.yaml`)와의 정합은 대조하지 않는다(정본 §7 드리프트 참조).
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import whymath_backend.db.models as models_pkg
from whymath_backend.db.base import Base

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ── 동결 입력 경로의 단일 진실 원천 ──────────────────────────────────────────
# 이 테스트가 읽는 파일 전부. `tests/infra/test_ci_contract_fixture_trigger_wiring.py`가
# `tests/backend/**`를 전수 스캔해 **이 상수를 AST로 파싱**하고 전건이 CI backend 잡 필터 안에
# 있는지 동결한다(OPS-62 — 종전에는 G0 동결 테스트 한 파일만 봐서 이 문서가 사각이었다·PR #997).
# ⚠️ 리터럴 튜플 형태를 유지할 것 — AST 파서가 문자열 상수만 읽는다(f-string·연산 금지).
FROZEN_INPUT_PATHS: tuple[str, ...] = ("docs/architecture/canonical_entity_model_v1.md",)

_CANON_DOC = _REPO_ROOT / FROZEN_INPUT_PATHS[0]
_CANON_HINT = f"정본 {_CANON_DOC.relative_to(_REPO_ROOT)} 를 갱신하고 이 상수를 함께 고쳐라."


def _load_all_models() -> None:
    """모든 모델 모듈을 적재해 `Base.metadata`를 완성한다(부분 적재면 측정이 새는다).

    `test_unit_structure_hypothesis_freeze.py` 선례 — `__init__` 수록 여부와 무관하게 pkgutil로
    전 모듈을 쓸어 담아, 새 모델 파일이 생겨도 측정 대상에 자동 포함되게 한다.
    """
    for module in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"whymath_backend.db.models.{module.name}")


# ──────────────────────────────────────────────────────────────────────────
# 동결 상수 — 정본 §1·§2 표와 1:1 (실측 2026-09-05·78테이블, SEC-27 job_ownership 추가로 79테이블,
# EOS-49가 concept_version을 Concept 좌석 4번째 테이블로 추가해 2026-09-14 80테이블로,
# EOS-103이 learner_state를 LearnerState 좌석 2번째 테이블로 추가해 2026-09-16 81테이블로 늘었다)
# ──────────────────────────────────────────────────────────────────────────

# 핵심 19종 → 좌석 테이블. 빈 tuple = **좌석 부재 동결**(정본 §3).
CANONICAL_ENTITY_SEATS: dict[str, tuple[str, ...]] = {
    "Subject": (),
    "Curriculum": ("curriculum_framework", "curriculum_version"),
    "CurriculumNode": (
        "curriculum_entry",
        "achievement_standard",
        "achievement_level_unit",
        "textbook_unit",
        "textbook_mapping",
    ),
    "LearningObjective": ("learning_objective", "unit_spec"),
    "Concept": ("concept", "concept_node", "atom_node", "concept_version"),
    "Skill": ("skill_node",),
    "Misconception": ("misconception_catalog",),
    "Problem": ("problem", "problem_step"),
    "Solution": ("solution_paths", "solution_nodes", "verified_solutions", "verified_lemmas"),
    "Hint": (),
    "Content": ("concept_content", "pedagogy_content_slot"),
    "Learner": ("user_profile",),
    "LearnerState": ("user_state_snapshot", "learner_state"),
    "MasteryState": ("concept_mastery_history", "skill_mastery_history", "ability_snapshot"),
    "Assessment": ("assessment",),
    "AssessmentResult": (),
    "LearningEvent": (
        "attempt_event",
        "evidence_event",
        "review_timer_event",
        "hint_usage",
        "answer_submission",
        "problem_attempt",
        "learning_session",
        "student_solution_step",
        "dead_end_log",
        "dialogue",
        "dialogue_turn",
    ),
    "PedagogyStrategy": ("strategy_node", "pedagogy_pack"),
    "ContentVersion": (),
}

# 핵심 19종에 배정하지 **않는** 테이블 → 배정 제외 사유(정본 §2-B).
# 사유를 값으로 강제해 "일단 여기에 던져 넣기"를 비싸게 만든다.
NON_CORE_TABLES: dict[str, str] = {
    # 임베딩 4종 — 개념/원자/오개념/문항 벡터. 노드 embedding 혼입 금지(플레이북 8대 원칙 ①).
    "atom_embedding": "임베딩(벡터) — 개념 노드에 혼입 금지",
    "concept_embedding": "임베딩(벡터) — 개념 노드에 혼입 금지",
    "misconception_embedding": "임베딩(벡터) — 오개념 노드에 혼입 금지",
    "problem_embedding": "임베딩(벡터) — 문항에 혼입 금지",
    # 관계·엣지 — 노드가 아니라 노드 사이. 관계 타입 폭발 방지 축.
    "concept_edge": "관계(엣지) — 개념↔개념",
    "concept_fusion": "관계(엣지) — 개념 융합",
    "concept_standard_link": "관계(엣지) — 개념↔성취기준",
    "problem_concept": "관계(엣지) — 문항↔개념",
    "problem_relation": "관계(엣지) — 문항↔문항",
    "misconception_relation": "관계(엣지) — 오개념↔오개념",
    "misconception_crosslink": "관계(엣지) — 오개념 kebab↔M-id 크로스워크",
    "evidence_links": "관계(엣지) — 증거↔대상",
    "derivation_edge": "관계(엣지) — 콘텐츠 파생 계보(권리 축)",
    # 부속 노드 — 핵심 19종의 하위 택소노미. 승격하려면 정본 갱신 경유.
    "formula_node": "부속 노드(공식 택소노미) — Concept 승격은 정본 갱신 경유",
    "problem_type_node": "부속 노드(문항유형 택소노미) — Problem 승격은 정본 갱신 경유",
    "atom_probe": "부속 노드(원자 프로브) — 원자 백본 진단 보조",
    # 렌더러 — 개념 노드에 renderer 혼입 금지(Concept Purity).
    "concept_visual_style": "렌더러(시각 스타일) — 개념 노드에 혼입 금지",
    "concept_visualization": "렌더러(시각화 인텐트) — 개념 노드에 혼입 금지",
    # 권리·출처 — 저작권 레일. 콘텐츠 본문이 아니라 그 출처·권리.
    "source_entity": "권리·출처(저작권 레일)",
    "rights_holder": "권리·출처(저작권 레일)",
    "rights_entity": "권리·출처(저작권 레일)",
    "content_source": "권리·출처(저작권 레일)",
    "content_rights": "권리·출처(저작권 레일)",
    "content_provenance": "권리·출처(생성 계보)",
    "generation_log": "권리·출처(LLM 생성 로그)",
    # 인증·법령 — 학습 도메인이 아니라 계정·동의.
    "refresh_token_session": "인증(세션 토큰)",
    "device_credential": "인증(기기 자격)",
    "parental_consent": "법령(법정대리인 동의) — 기계 대체 금지 축",
    # 감사·운영 — 횡단 관심사(7계층 밖).
    "deletion_audit": "감사(파기 이력)",
    "privacy_audit": "감사(개인정보 접근)",
    "defect_report": "운영(결함 신고)",
    # 집계 시계열 — 원시 이벤트의 파생. LearningEvent가 원천이고 이쪽은 롤업.
    "daily_learning_metrics": "집계(롤업) — LearningEvent 파생물",
    "problem_solve_time_distribution": "집계(롤업) — LearningEvent 파생물",
    "user_behavior_metrics": "집계(롤업) — LearningEvent 파생물",
    # 사용자 이력 — Learner의 변경 이력이지 상태(LearnerState)가 아니다.
    "user_track_history": "사용자 이력(트랙 변경) — LearnerState 아님",
    "user_persona_history": "사용자 이력(페르소나 변경) — LearnerState 아님",
    # 판정 보류 — 날조 금지(정본 §2-C). Misconception(카탈로그)도 LearningEvent(원시)도 아니다.
    "misconception_hypothesis": "판정 보류 — L2 오개념 추론 산출물. 카탈로그도 원시 이벤트도 아니다",
    # SEC-27: 비동기 작업 소유권 — 학습 도메인 엔티티가 아니라 서버 내부 인가 메타(refresh_
    # token_session·device_credential과 동형 — 인증·법령 그룹에 편입).
    "job_ownership": "인증(작업 소유권) — 학습 도메인 엔티티 아님",
}

# 좌석 부재 4종(정본 §3) — **좌석 tuple이 비어 있다는 사실 자체**를 동결한다.
# 아래 RESERVED_ABSENT_TABLE_NAMES는 *이름을 맞힌 경우만* 잡으므로, 예약어를 피한 이름
# (`hint_content` 등)을 좌석에 등재하면 그대로 통과한다 — 그 구멍을 이 상수가 막는다.
ABSENT_ENTITIES: frozenset[str] = frozenset(
    {"Subject", "Hint", "AssessmentResult", "ContentVersion"}
)

# 좌석 부재 4종이 테이블을 얻으려 할 때 쓸 법한 이름 — 하나라도 생기면 RED.
# 전수 귀속 검사(①)도 잡지만, 이쪽은 *어느 동결 결정을 깼는지*를 이름으로 지목한다.
RESERVED_ABSENT_TABLE_NAMES: dict[str, str] = {
    "subject": "Subject",
    "subjects": "Subject",
    "hint": "Hint",
    "hints": "Hint",
    "assessment_result": "AssessmentResult",
    "assessment_results": "AssessmentResult",
    "content_version": "ContentVersion",
    "content_versions": "ContentVersion",
    "entity_version": "ContentVersion",
}

# 힌트 **본문** 컬럼 예약(ARCH-39 · 2026-09-06) — 좌석이 *조용히* 생기는 것을 막는다.
#
# ⚠ 이것은 **금지가 아니라 명시적 결정 요구**다(2026-09-07 정정). `hints` 좌석의 신설은
# `S4-11-hint-content-generation`(P0·todo)이 소유하며, 그 태스크는 아래 상수와
# `RESERVED_ABSENT_TABLE_NAMES`·`ABSENT_ENTITIES`의 `Hint` 항목을 **의도적으로 걷어내면서**
# 착수한다(다른 부재 4종과 같은 규약). 한때 이 주석이 "영구 부재"라고 적혀 있었으나 그 판정은
# 틀렸다 — 좌석은 포기된 것이 아니라 연기된 것이다.
#
# 위 두 검사(③ 이름 예약 · ③-b 좌석 tuple)는 둘 다 **테이블** 축이다. 그런데 Hint 좌석을
# 우회하는 가장 값싼 길은 새 테이블이 아니라 **기존 테이블에 컬럼 하나를 더하는 것**이다
# (`problem_step.hint_text` 같은 형태) — 그러면 새 테이블이 없으니 ③이 안 잡고, Hint의 좌석
# tuple도 비어 있는 채라 ③-b도 안 잡는다. 판정 근거 ⑵("본문을 담는 좌석이 없다")가 조용히
# 깨지는 자리다. 이 검사가 그 축을 막는다.
#
# 판정이 막는 것은 **본문**이지 힌트 *메타*가 아니다 — 아래 허용 목록은 판정과 무관하게
# 실재하는 컬럼들이고, 오히려 이들이 있어서 KPI가 본문 없이 측정된다(정본 §3-B 근거 ⑶).
_HINT_BODY_COLUMN_TOKENS: tuple[str, ...] = ("text", "content", "body", "message", "prompt")
_ALLOWED_HINT_COLUMNS: dict[str, str] = {
    "used_hint": "힌트 사용 여부(불리언) — 본문 아님",
    "hint_id": "느슨참조 식별자 — 본문 아님(정본 §3-B 부수 판정)",
    "hint_level": "graded 단계 1~4 — KPI ⑧의 측정 축",
    "hint_usage_id": "hint_usage PK",
}


_SEAT_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*\*\*(\w+)\*\*\s*\|(.*?)\|\s*(\d+)\s*\|\s*$")
_NON_CORE_ROW_RE = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*(.+?)\s*\|\s*$")
_TABLE_TOKEN_RE = re.compile(r"`([a-z_]+)`")

_SEC_2A = "### §2-A. 좌석 배정"
_SEC_2B = "### §2-B. 핵심 외"
_SEC_2C = "### §2-C. 판정 보류"


def _doc_text() -> str:
    assert _CANON_DOC.is_file(), f"정본 문서가 없다: {_CANON_DOC}"
    return _CANON_DOC.read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str) -> str:
    """정본의 한 절만 잘라 낸다 — 문서 전역 토큰 검색이 아니라 *그 표*만 본다."""
    i, j = text.find(start), text.find(end)
    assert i != -1, f"정본에서 절 머리를 찾지 못했다: {start!r}"
    assert j > i, f"정본 절 순서가 어긋났다: {start!r} → {end!r}"
    return text[i:j]


def _parse_doc_seats() -> dict[str, tuple[frozenset[str], int]]:
    """§2-A 표 → {엔티티: (좌석 집합, 표에 적힌 좌석 수)}."""
    rows: dict[str, tuple[frozenset[str], int]] = {}
    for line in _slice(_doc_text(), _SEC_2A, _SEC_2B).splitlines():
        m = _SEAT_ROW_RE.match(line)
        if m:
            rows[m.group(1)] = (frozenset(_TABLE_TOKEN_RE.findall(m.group(2))), int(m.group(3)))
    return rows


def _parse_doc_non_core() -> set[str]:
    """§2-B 표 → 핵심-외 테이블 이름 집합."""
    section = _slice(_doc_text(), _SEC_2B, _SEC_2C)
    return {m.group(1) for line in section.splitlines() if (m := _NON_CORE_ROW_RE.match(line))}


def _seated_tables() -> set[str]:
    return {table for seats in CANONICAL_ENTITY_SEATS.values() for table in seats}


# ──────────────────────────────────────────────────────────────────────────
# ① 전수 귀속 — 새 테이블이 생기면 RED
# ──────────────────────────────────────────────────────────────────────────
def test_every_table_is_attributed() -> None:
    """실제 `Base.metadata` 전 테이블이 좌석 또는 핵심-외 중 정확히 한쪽에 배정돼 있다."""
    _load_all_models()
    actual = set(Base.metadata.tables)
    declared = _seated_tables() | set(NON_CORE_TABLES)

    unattributed = sorted(actual - declared)
    assert not unattributed, (
        f"귀속 없는 신규 테이블 {len(unattributed)}건: {unattributed}\n"
        f"9월 스키마 노드 폭발 방지 동결이다 — 자동 통과시키지 말고 {_CANON_HINT}"
    )

    vanished = sorted(declared - actual)
    assert (
        not vanished
    ), f"정본이 선언한 테이블이 코드에 없다 {len(vanished)}건: {vanished}\n{_CANON_HINT}"


def test_seat_and_non_core_do_not_overlap() -> None:
    """한 테이블이 좌석이면서 동시에 핵심-외일 수 없다(배정은 배타적)."""
    overlap = sorted(_seated_tables() & set(NON_CORE_TABLES))
    assert not overlap, f"이중 배정 {overlap} — 좌석과 핵심-외 중 하나만 골라라"


# ──────────────────────────────────────────────────────────────────────────
# ② 좌석 실재 — 좌석 삭제·개명이 무증상으로 지나가지 못한다
# ──────────────────────────────────────────────────────────────────────────
def test_canonical_entity_list_is_frozen_at_nineteen() -> None:
    """핵심 엔티티는 19종이다 — 늘리거나 줄이려면 정본 갱신을 경유한다."""
    assert (
        len(CANONICAL_ENTITY_SEATS) == 19
    ), f"핵심 엔티티가 {len(CANONICAL_ENTITY_SEATS)}종이 됐다 — {_CANON_HINT}"


def test_every_seat_table_exists_in_metadata() -> None:
    """19종의 좌석 테이블이 전부 실재한다(좌석 부재 4종은 검사 대상 아님)."""
    _load_all_models()
    actual = set(Base.metadata.tables)
    missing = {
        entity: sorted(set(seats) - actual)
        for entity, seats in CANONICAL_ENTITY_SEATS.items()
        if set(seats) - actual
    }
    assert not missing, f"좌석 테이블이 사라졌다(삭제·개명 추정): {missing}\n{_CANON_HINT}"


# ──────────────────────────────────────────────────────────────────────────
# ③ 좌석 부재 동결 — 4종이 몰래 좌석을 얻지 못한다
# ──────────────────────────────────────────────────────────────────────────
def test_absent_entities_have_no_seat_table() -> None:
    """정본 §3의 좌석 부재 4종에 예약된 테이블 이름이 등장하면 RED."""
    _load_all_models()
    actual = set(Base.metadata.tables)
    breached = {
        name: entity for name, entity in RESERVED_ABSENT_TABLE_NAMES.items() if name in actual
    }
    assert not breached, (
        f"좌석 부재 동결이 깨졌다: {breached}\n"
        f"부재는 실수가 아니라 결정이다(정본 §3) — 되돌리려면 {_CANON_HINT}"
    )


# ──────────────────────────────────────────────────────────────────────────
# ③-b 좌석 부재 동결 — 예약어를 피한 이름으로도 좌석을 얻지 못한다
# ──────────────────────────────────────────────────────────────────────────
def test_absent_entities_keep_empty_seats() -> None:
    """정본 §3의 4종은 좌석 tuple이 **비어 있어야** 한다.

    바로 위 예약어 검사(③)는 *이름을 맞힌 경우만* 잡는다 — `hint_content`처럼 예약어를 피한
    이름을 좌석에 등재하면 전수 귀속·좌석 실재·문서 정합을 전부 만족하며 통과한다(실측 확인).
    이 검사는 이름이 아니라 **배정 그 자체**를 보므로 그 우회로를 닫는다.
    """
    unknown = sorted(ABSENT_ENTITIES - set(CANONICAL_ENTITY_SEATS))
    assert not unknown, f"부재 선언에 없는 엔티티가 적혀 있다: {unknown}"

    breached = {
        e: CANONICAL_ENTITY_SEATS[e] for e in sorted(ABSENT_ENTITIES) if CANONICAL_ENTITY_SEATS[e]
    }
    assert not breached, (
        f"좌석 부재 동결이 깨졌다(좌석 등재됨): {breached}\n"
        f"부재는 실수가 아니라 결정이다(정본 §3) — 되돌리려면 {_CANON_HINT}"
    )


# ──────────────────────────────────────────────────────────────────────────
# ③-c 좌석 부재 동결 — 컬럼 축(ARCH-39). 테이블을 안 만들고 컬럼만 더하는 우회로를 닫는다
# ──────────────────────────────────────────────────────────────────────────
def test_no_table_gains_a_hint_body_column() -> None:
    """어느 테이블도 힌트 **본문** 컬럼을 갖지 않는다(정본 §3-B).

    좌석 부재를 우회하는 가장 값싼 길은 `hints` 테이블이 아니라 **기존 테이블의 컬럼 하나**이며,
    위 ③·③-b는 둘 다 테이블 축이라 그것을 보지 못한다(실측: `problem_step`에 `hint_text`를
    더해도 둘 다 통과한다). 좌석 신설은 결정 사항이지 우연이어서는 안 되므로 이 축을 막는다.

    판정은 문자열이 아니라 **구성된 결과**를 본다(CLAUDE.md 2026-09-01 ①) — 소스 grep이
    아니라 `Base.metadata`의 실제 컬럼 목록을 훑는다. 이름에 `hint`가 들어가면서 본문을
    시사하는 토큰(text/content/body/…)을 함께 가진 컬럼만 위반이고, 힌트 *메타* 컬럼
    4종은 허용 목록으로 명시한다(과잉 차단 금지 — 그 컬럼들이 있어서 KPI가 성립한다).
    """
    _load_all_models()
    scanned = 0
    breached: dict[str, str] = {}
    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            scanned += 1
            name = column.name
            if "hint" not in name or name in _ALLOWED_HINT_COLUMNS:
                continue
            if any(token in name for token in _HINT_BODY_COLUMN_TOKENS):
                breached[f"{table_name}.{name}"] = "힌트 본문 컬럼"

    # 스캔 0건은 통과가 아니라 측정 실패다(CLAUDE.md 2026-09-01 ④).
    assert scanned > 0, (
        "메타데이터에서 컬럼을 한 개도 보지 못했다 — 모델 적재가 새고 있다. "
        "0건 통과와 측정 실패는 같은 색이면 안 된다."
    )
    assert not breached, (
        f"Hint 좌석 부재 동결이 컬럼 축에서 깨졌다: {breached}\n"
        f"힌트 본문 좌석의 신설은 `S4-11-hint-content-generation`이 소유한다(정본 §3-B) — "
        f"의도한 신설이면 {_CANON_HINT}"
    )


# ──────────────────────────────────────────────────────────────────────────
# ④ 문서 정합 — 이름 존재가 아니라 *배정*을 대조한다
# ──────────────────────────────────────────────────────────────────────────
def test_canon_doc_seat_assignments_match_constants() -> None:
    """§2-A 표의 엔티티→좌석 배정이 상수와 **정확히** 일치한다.

    토큰이 문서 어딘가에 있기만 하면 통과하는 검사는, 배정을 옮겨도(예: `skill_node`를 Skill →
    Content) 같은 초록을 낸다 — 정본과 집행이 어긋난 채로. 그래서 표를 파싱해 대조한다.
    """
    parsed = _parse_doc_seats()
    expected = {e: (frozenset(seats), len(seats)) for e, seats in CANONICAL_ENTITY_SEATS.items()}

    assert set(parsed) == set(expected), (
        f"§2-A 표의 엔티티 목록이 상수와 다르다 — 문서에만: {sorted(set(parsed) - set(expected))} · "
        f"상수에만: {sorted(set(expected) - set(parsed))}\n{_CANON_HINT}"
    )

    mismatched = {
        entity: {"문서": sorted(parsed[entity][0]), "상수": sorted(expected[entity][0])}
        for entity in expected
        if parsed[entity][0] != expected[entity][0]
    }
    assert not mismatched, f"§2-A 좌석 배정이 상수와 어긋난다: {mismatched}\n{_CANON_HINT}"

    bad_counts = {
        entity: {"표기": parsed[entity][1], "실제": expected[entity][1]}
        for entity in expected
        if parsed[entity][1] != expected[entity][1]
    }
    assert not bad_counts, f"§2-A '좌석 수' 열이 실제와 다르다: {bad_counts}"


def test_canon_doc_non_core_table_matches_constants() -> None:
    """§2-B 표의 핵심-외 목록이 상수와 정확히 일치한다."""
    parsed = _parse_doc_non_core()
    expected = set(NON_CORE_TABLES)
    assert parsed == expected, (
        f"§2-B 표가 상수와 다르다 — 문서에만: {sorted(parsed - expected)} · "
        f"상수에만: {sorted(expected - parsed)}\n{_CANON_HINT}"
    )
