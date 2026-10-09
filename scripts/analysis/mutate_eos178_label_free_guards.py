#!/usr/bin/env python3
"""EOS-178 라벨-단독 공급 분리 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 "숙달 라벨 '초보'만으로 올라간 힌트 단계(학생 신호 없음·검수 힌트 미실림)를 힌트 귀속에서
도움으로 세지 않는다"는 결정이 만든 일곱 곳이다(판정문
`docs/reviews/eos178_beginner_label_hint_judgment_2026-10-06.md`):

- `l4/hint_deferral.py` — 도움 공급 진리표 · 라벨 없는 단계(`decide_base_hint_level`)
- `l4/polya/engine.py` — 결정이 base·적용 라벨을 운반하는 지점
- `l4/models.py` — 두 계측 필드가 응답 본문으로 새지 않게 하는 `exclude`
- `schema/event_data_contract.py` — 원장 필드의 범위
- `api/coach.py` — 원장 판독 · 귀속 분기 · 킬 스위치 · 적재(두 핸들러)
- `config.py` — 킬 스위치 기본값
- `ops/recommendation_reach_report.py` — §7 공급 구성의 SQL·분모

규율은 선례 `scripts/analysis/mutate_eos39_help_fold_guards.py`와 같다 — 주입 실재 단언(앵커 1건 ·
치환 후 원본과 다름 · 쓴 내용 재확인 · 구문 검사) · 순수 Python 치환(셸 heredoc 주입 0) · 백업
**복사** 원복(git 원복 금지)과 바이트 동일성 단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 ·
판정은 pytest 종료 코드 · `skipped`가 든 실행은 무효 · 실행마다 대상 모듈의 바이트코드 캐시 삭제와
`PYTHONDONTWRITEBYTECODE=1` · 실행 전후 sha256 대조.

**각 뮤테이션은 서로 다른 절을 깬다** — "이 절이 없으면 어떤 입력이 통과하는가"에 답하는 반례가
테스트 픽스처에 있어야 그 뮤테이션이 RED가 된다(MISC-07·MISC-23 교훈). 이 하네스를 설계하며 **등가
뮤턴트 2건**(결과가 같아 어떤 테스트도 못 잡는 절)을 찾아 코드에서 걷어냈다: ① 신호 없는 쌍 판정의
`coalesce(has_signal, False)` — 라벨-단독 행이 있는 쌍은 `base_level`을 가진 행이 반드시 있어 NULL이
아니다 ② 서빙 판정의 `hint_id IS NOT NULL` — `NULL != ''`가 NULL이라 `!= ''` 하나로 같은 결과다.
같은 종류가 일부만 RED면 하네스를 의심한다.

표면이 둘이다:

- **단위**(기본): 순수 진리표 · 엔진 운반 · 직렬화 제외 · 계약 범위 · 귀속 행 단위 · 킬 스위치 ·
  원장 적재 · 리포트 순수 집계 · 기존 귀속 테스트.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP 통합
  `tests/backend/api/test_eos178_label_free_attribution_integration.py`. 환경변수
  `WHYMATH_DATABASE_URL`(asyncpg URL · **이 브랜치의 head까지 마이그레이션된 DB**)이 필요하다.
  핸들러 두 곳의 적재 결선과 리포트 §7의 실 JSONB·`bool_or` SQL은 이 표면에서만 잡힌다.

사용:
    python3 scripts/analysis/mutate_eos178_label_free_guards.py \
        [--with-integration] [--only 이름조각]

종료 코드 0 = 전건 검출 · 1 = 생존한 뮤테이션 있음(가드가 위장이다) 또는 대조군 RED.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "src" / "backend"
PKG = BACKEND / "whymath_backend"

HD = PKG / "l4" / "hint_deferral.py"
ENG = PKG / "l4" / "polya" / "engine.py"
MOD = PKG / "l4" / "models.py"
EDC = PKG / "schema" / "event_data_contract.py"
COACH = PKG / "api" / "coach.py"
CFG = PKG / "config.py"
RR = PKG / "ops" / "recommendation_reach_report.py"

UNIT_TESTS = [
    "../../tests/backend/l4/test_eos178_label_free_hint_level.py",
    "../../tests/backend/api/test_eos178_label_free_attribution.py",
    "../../tests/backend/api/test_coach_hint_attribution.py",
    "../../tests/backend/ops/test_recommendation_reach_report.py",
    "../../tests/backend/schema/test_event_data_contract.py",
]
INTEGRATION_TESTS = ["../../tests/backend/api/test_eos178_label_free_attribution_integration.py"]


@dataclass(frozen=True)
class Mutation:
    """뮤테이션 1건 — 어느 파일의 어느 절(들)을 무엇으로 바꾸는가 + 어느 표면이 RED여야 하는가."""

    name: str
    path: Path
    edits: tuple[tuple[str, str], ...]  # (앵커, 치환) — 앵커는 각각 1건이어야 한다
    axis: str  # 이 뮤테이션이 검사하는 축(보고용)
    integration: bool = False  # True면 실 PG 서빙 경로 표면에서 판정한다


def m(name: str, path: Path, old: str, new: str, axis: str, integration: bool = False) -> Mutation:
    return Mutation(name, path, ((old, new),), axis, integration)


# ── 앵커(원문 그대로 — 1건이어야 한다) ───────────────────────────────────────────────
_HS_FLOOR = "    if not counts_as_hint_usage(hint_level):\n        return False\n"
_HS_LEGACY = "    if base_level is None:\n        return True\n"
_HS_SIGNAL = "    if counts_as_hint_usage(base_level):\n        return True\n    return served\n"
_BASE_CALL = (
    "        student_input=student_input,\n"
    "        turn_count=turn_count,\n"
    "        prev_hint_level=prev_hint_level,\n"
    "        mastery_level=None,\n"
)

_ENG_BASE = (
    "        base_hint_level = decide_base_hint_level(\n"
    "            student_input=student_input,\n"
    "            turn_count=state.turn_count,\n"
    "            prev_hint_level=state.prev_hint_level,\n"
    "        )\n"
)
_ENG_BASE_FIELD = "            base_hint_level=base_hint_level,\n"
_ENG_LABEL_FIELD = "            applied_mastery_level=mastery_level,\n"

_MOD_BASE = (
    "    base_hint_level: Literal[1, 2, 3, 4] | None = Field(\n"
    "        default=None,\n"
    "        exclude=True,\n"
)
_MOD_LABEL = (
    "    applied_mastery_level: str | None = Field(\n        default=None,\n        exclude=True,\n"
)

_EDC_BASE = (
    "    base_level: int | None = Field(\n        default=None,\n        ge=1,\n        le=4,\n"
)
_EDC_LABEL_MAX = "        max_length=16,\n"

_CO_BASE_READ = '    level = payload.get("base_level")\n'
_CO_SERVED = "    return isinstance(hint_id, str) and bool(hint_id)\n"
_CO_SWITCH = "    label_free = get_settings().l4_hint_attribution_label_free_enabled\n"
_CO_COND = "            base_level=_supplied_base_level(payload) if label_free else None,\n"
_CO_SERVED_ARG = "            served=_served_hint_marked(payload),\n"
_CO_LOG_BASE = "            base_level=base_hint_level,\n"
_CO_LOG_LABEL = "            ability_level=ability_level,\n"

_CALL_TAIL = (
    "        mode=body.mode,\n"
    "        persona=event_persona,\n"
    "        client_state_mismatch=bool(mismatch_fields),\n"
    "        turn_handled=completion.handled,\n"
    "        served_hint=served_hint,\n"
)
_BASE_ARG = "        base_hint_level=decision.base_hint_level,\n"
_LABEL_ARG = "        ability_level=decision.applied_mastery_level,\n"
_CREATE_HEAD = (
    "        problem_id=body.problem_id,\n"
    "        attempt_id=dialogue.attempt_id,\n"
    "        hint_level=decision.hint_level,\n"
)
_APPEND_HEAD = (
    "        problem_id=dialogue.problem_id,\n"
    "        attempt_id=dialogue.attempt_id,\n"
    "        hint_level=decision.hint_level,\n"
)
_CALL_CREATE = _CREATE_HEAD + _CALL_TAIL + _BASE_ARG + _LABEL_ARG
_CALL_APPEND = _APPEND_HEAD + _CALL_TAIL + _BASE_ARG + _LABEL_ARG

_CFG_DEFAULT = "    l4_hint_attribution_label_free_enabled: bool = Field(\n        default=True,\n"

_RR_FLOOR = "        .where(AttemptEvent.event_type == EventType.힌트제공, supply_level >= 2)\n"
_RR_CLASSIFIED = "    supply_classified_total = await _count_supply(supply_base.isnot(None))\n"
_RR_LABEL_ONLY = "    supply_label_only_total = await _count_supply(supply_base < 2)\n"
_RR_SERVED = (
    "    supply_label_only_served_total = await _count_supply(supply_base < 2, supply_served != "
    '"")\n'
)
_RR_GROUP_SELECT = (
    "            AttemptEvent.user_id,\n"
    "            AttemptEvent.problem_id,\n"
    '            func.bool_or(and_(supply_level >= 2, supply_base < 2)).label("has_label_only"),\n'
)
_RR_GROUP_BY = "        .group_by(AttemptEvent.user_id, AttemptEvent.problem_id)\n"
_RR_PAIR_TYPE = (
    "        .where(AttemptEvent.event_type == EventType.힌트제공)\n"
    "        .group_by(AttemptEvent.user_id, AttemptEvent.problem_id)\n"
)
_RR_LABEL_ONLY_AND = (
    '            func.bool_or(and_(supply_level >= 2, supply_base < 2)).label("has_label_only"),\n'
)
_RR_SIGNAL = '            func.bool_or(supply_base >= 2).label("has_signal"),\n'
_RR_PAIR_FILTER = (
    "        select(func.count()).select_from(pair_stats)"
    ".where(pair_stats.c.has_label_only.is_(True))\n"
)
_RR_UNSIGNALED = "label_only_pair_stmt.where(pair_stats.c.has_signal.is_(False))"
_RR_RATE_CLASSIFIED = (
    "            counts.coach_supply_classified_row_total, counts.coach_supply_help_row_total\n"
)
_RR_RATE_LABEL_ONLY = (
    "            counts.coach_supply_label_only_row_total,"
    " counts.coach_supply_classified_row_total\n"
)
_RR_RATE_SERVED = (
    "            counts.coach_supply_label_only_served_row_total,\n"
    "            counts.coach_supply_label_only_row_total,\n"
)
_RR_RATE_UNSIGNALED = (
    "            counts.coach_label_only_unsignaled_pair_total,"
    " counts.coach_label_only_pair_total\n"
)


MUTATIONS: list[Mutation] = [
    # ── 축 1: 도움 공급 진리표 ─────────────────────────────────────────────────────
    m(
        "H01-below-two-floor-dropped",
        HD,
        _HS_FLOOR,
        "",
        "최종 단계 2 미만은 도움이 아니다('숙달' 완화로 내려간 신호 턴)",
    ),
    m(
        "H02-legacy-row-not-counted",
        HD,
        _HS_LEGACY,
        "    if base_level is None:\n        return False\n",
        "구판 행(base 모름)은 종전 규칙으로 센다",
    ),
    m(
        "H03-signal-row-not-counted",
        HD,
        _HS_SIGNAL,
        "    if counts_as_hint_usage(base_level):\n        return False\n    return served\n",
        "신호가 올린 공급은 도움이다",
    ),
    m(
        "H04-served-hint-ignored",
        HD,
        _HS_SIGNAL,
        "    if counts_as_hint_usage(base_level):\n        return True\n    return False\n",
        "라벨-단독이어도 검수 힌트가 실렸으면 도움이다",
    ),
    m(
        "H05-label-only-always-counted",
        HD,
        _HS_SIGNAL,
        "    if counts_as_hint_usage(base_level):\n        return True\n    return True\n",
        "라벨-단독 공급을 세지 않는다(분리의 핵심)",
    ),
    # ── 축 2: 라벨 없는 단계 ──────────────────────────────────────────────────────
    m(
        "B01-base-takes-the-label",
        HD,
        _BASE_CALL,
        _BASE_CALL.replace("mastery_level=None,", 'mastery_level="초보",'),
        "base는 라벨 없이 계산한다(진실원천 하나)",
    ),
    m(
        "B02-base-ignores-turn-count",
        HD,
        _BASE_CALL,
        _BASE_CALL.replace("turn_count=turn_count,", "turn_count=0,"),
        "base가 5회+ 막힘 신호를 본다(격자)",
    ),
    m(
        "B03-base-ignores-prev-level",
        HD,
        _BASE_CALL,
        _BASE_CALL.replace("prev_hint_level=prev_hint_level,", "prev_hint_level=None,"),
        "base가 이전 단계를 본다(격자)",
    ),
    # ── 축 3: 엔진이 base·라벨을 운반 ─────────────────────────────────────────────
    m(
        "E01-engine-base-is-the-final-level",
        ENG,
        _ENG_BASE,
        "        base_hint_level = hint_level\n",
        "엔진의 base가 최종 단계의 복사가 아니다",
    ),
    m(
        "E02-engine-base-not-carried",
        ENG,
        _ENG_BASE_FIELD,
        "",
        "결정이 base를 들고 나간다",
    ),
    m(
        "E03-engine-label-not-carried",
        ENG,
        _ENG_LABEL_FIELD,
        "",
        "결정이 적용된 라벨을 들고 나간다",
    ),
    m(
        "E04-engine-base-ignores-turn-count",
        ENG,
        _ENG_BASE,
        _ENG_BASE.replace("turn_count=state.turn_count,", "turn_count=0,"),
        "엔진의 base가 단계 내 턴 수를 본다",
    ),
    m(
        "E05-engine-base-ignores-prev-level",
        ENG,
        _ENG_BASE,
        _ENG_BASE.replace("prev_hint_level=state.prev_hint_level,", "prev_hint_level=None,"),
        "엔진의 base가 직전 단계를 본다",
    ),
    # ── 축 4: 응답 본문으로 새지 않음 ─────────────────────────────────────────────
    m(
        "X01-base-leaks-into-the-response",
        MOD,
        _MOD_BASE,
        _MOD_BASE.replace("        exclude=True,\n", ""),
        "base가 직렬화에서 제외된다",
    ),
    m(
        "X02-label-leaks-into-the-response",
        MOD,
        _MOD_LABEL,
        _MOD_LABEL.replace("        exclude=True,\n", ""),
        "적용 라벨이 직렬화에서 제외된다",
    ),
    # ── 축 5: 원장 계약 ──────────────────────────────────────────────────────────
    m(
        "D01-base-field-renamed",
        EDC,
        _EDC_BASE,
        _EDC_BASE.replace("base_level:", "base_level_x:"),
        "원장 계약에 base_level 좌석이 있다",
    ),
    m(
        "D02-base-upper-bound-dropped",
        EDC,
        _EDC_BASE,
        _EDC_BASE.replace("        le=4,\n", "        le=40,\n"),
        "base_level의 상한(4)",
    ),
    m(
        "D03-base-lower-bound-dropped",
        EDC,
        _EDC_BASE,
        _EDC_BASE.replace("        ge=1,\n", "        ge=-9,\n"),
        "base_level의 하한(1)",
    ),
    m(
        "D04-label-length-unbounded",
        EDC,
        _EDC_LABEL_MAX,
        "        max_length=160,\n",
        "ability_level의 길이 상한",
    ),
    # ── 축 6: 귀속 분기 · 킬 스위치 · 원장 판독 ───────────────────────────────────
    m(
        "C01-base-read-from-the-wrong-key",
        COACH,
        _CO_BASE_READ,
        '    level = payload.get("hint_level")\n',
        "원장의 base_level 키를 읽는다",
    ),
    m(
        "C02-empty-hint-id-counts-as-served",
        COACH,
        _CO_SERVED,
        "    return isinstance(hint_id, str)\n",
        "빈 hint_id는 실린 힌트가 아니다",
    ),
    m(
        "C03-switch-read-replaced-by-true",
        COACH,
        _CO_SWITCH,
        "    label_free = True\n",
        "킬 스위치를 읽는다(끄면 EOS-133 규칙)",
    ),
    m(
        "C04-switch-not-applied-to-base",
        COACH,
        _CO_COND,
        "            base_level=_supplied_base_level(payload),\n",
        "킬 스위치가 base 읽기를 끊는다",
    ),
    m(
        "C05-served-marker-dropped",
        COACH,
        _CO_SERVED_ARG,
        "            served=False,\n",
        "귀속이 서빙 표지를 판정에 넘긴다",
    ),
    m(
        "C06-ledger-base-not-written",
        COACH,
        _CO_LOG_BASE,
        "            base_level=None,\n",
        "원장 적재 함수가 base를 쓴다",
    ),
    m(
        "C07-ledger-label-not-written",
        COACH,
        _CO_LOG_LABEL,
        "            ability_level=None,\n",
        "원장 적재 함수가 라벨을 쓴다",
    ),
    # ── 축 7: 서빙 경로 — 핸들러 두 곳의 적재 결선(통합에서만 잡힌다) ─────────────
    m(
        "S01-create-session-base-not-passed",
        COACH,
        _CALL_CREATE,
        _CALL_CREATE.replace(_BASE_ARG, ""),
        "세션 생성 핸들러가 base를 넘긴다",
        True,
    ),
    m(
        "S02-create-session-label-not-passed",
        COACH,
        _CALL_CREATE,
        _CALL_CREATE.replace(_LABEL_ARG, ""),
        "세션 생성 핸들러가 라벨을 넘긴다",
        True,
    ),
    m(
        "S03-append-turns-base-not-passed",
        COACH,
        _CALL_APPEND,
        _CALL_APPEND.replace(_BASE_ARG, ""),
        "턴 추가 핸들러가 base를 넘긴다",
        True,
    ),
    m(
        "S04-append-turns-label-not-passed",
        COACH,
        _CALL_APPEND,
        _CALL_APPEND.replace(_LABEL_ARG, ""),
        "턴 추가 핸들러가 라벨을 넘긴다",
        True,
    ),
    # ── 축 8: 킬 스위치 기본값 ────────────────────────────────────────────────────
    m(
        "G01-switch-default-off",
        CFG,
        _CFG_DEFAULT,
        _CFG_DEFAULT.replace("default=True", "default=False"),
        "분리가 기본 ON이다(정식기능)",
    ),
    # ── 축 9: 리포트 §7 — 순수 집계의 분모 ────────────────────────────────────────
    m(
        "R01-classified-rate-wrong-denominator",
        RR,
        _RR_RATE_CLASSIFIED,
        "            counts.coach_supply_classified_row_total,"
        " counts.coach_supply_label_only_row_total\n",
        "분류 가능 비율의 분모(단계 2+ 행)",
    ),
    m(
        "R02-label-only-rate-wrong-denominator",
        RR,
        _RR_RATE_LABEL_ONLY,
        "            counts.coach_supply_label_only_row_total,"
        " counts.coach_supply_help_row_total\n",
        "라벨-단독 비율의 분모(분류된 행)",
    ),
    m(
        "R03-served-rate-wrong-denominator",
        RR,
        _RR_RATE_SERVED,
        "            counts.coach_supply_label_only_served_row_total,\n"
        "            counts.coach_supply_classified_row_total,\n",
        "서빙 비율의 분모(라벨-단독 행)",
    ),
    m(
        "R04-unsignaled-rate-wrong-denominator",
        RR,
        _RR_RATE_UNSIGNALED,
        "            counts.coach_label_only_unsignaled_pair_total, "
        "counts.coach_supply_label_only_row_total\n",
        "신호 없는 쌍 비율의 분모(라벨-단독 쌍)",
    ),
    # ── 축 10: 리포트 §7 — 실 JSONB·bool_or SQL(통합에서만 잡힌다) ─────────────────
    m(
        "Q01-supply-floor-includes-direction-rows",
        RR,
        _RR_FLOOR,
        _RR_FLOOR.replace("supply_level >= 2", "supply_level >= 1"),
        "단계 2+ 행만 도움 후보다(방향 행 제외)",
        True,
    ),
    m(
        "Q02-classified-includes-legacy-rows",
        RR,
        _RR_CLASSIFIED,
        "    supply_classified_total = await _count_supply()\n",
        "분류 가능 = base_level이 실린 행",
        True,
    ),
    m(
        "Q03-label-only-boundary-off-by-one",
        RR,
        _RR_LABEL_ONLY,
        _RR_LABEL_ONLY.replace("supply_base < 2", "supply_base <= 2"),
        "라벨-단독 경계(base < 2)",
        True,
    ),
    m(
        "Q04-served-condition-dropped",
        RR,
        _RR_SERVED,
        "    supply_label_only_served_total = await _count_supply(supply_base < 2)\n",
        "서빙된 라벨-단독 = 비어 있지 않은 hint_id",
        True,
    ),
    Mutation(
        "Q05-pair-not-split-by-problem",
        RR,
        (
            (
                _RR_GROUP_SELECT,
                "            AttemptEvent.user_id,\n"
                "            func.bool_or(and_(supply_level >= 2, supply_base < 2))"
                '.label("has_label_only"),\n',
            ),
            (_RR_GROUP_BY, "        .group_by(AttemptEvent.user_id)\n"),
        ),
        "쌍은 (학생·문항)이다 — 학생 단위로 합치지 않는다",
        True,
    ),
    m(
        "Q06-pair-event-type-filter-dropped",
        RR,
        _RR_PAIR_TYPE,
        "        .group_by(AttemptEvent.user_id, AttemptEvent.problem_id)\n",
        "쌍 집계가 공급 원장(힌트제공)만 본다",
        True,
    ),
    m(
        "Q07-pair-label-only-ignores-level-floor",
        RR,
        _RR_LABEL_ONLY_AND,
        '            func.bool_or(supply_base < 2).label("has_label_only"),\n',
        "라벨-단독 행 = 단계 2+ ∧ base<2(방향 행 제외)",
        True,
    ),
    m(
        "Q08-signal-boundary-off-by-one",
        RR,
        _RR_SIGNAL,
        '            func.bool_or(supply_base > 2).label("has_signal"),\n',
        "학생 신호 경계(base >= 2)",
        True,
    ),
    m(
        "Q09-pair-count-not-filtered-to-label-only",
        RR,
        _RR_PAIR_FILTER,
        "        select(func.count()).select_from(pair_stats)\n",
        "라벨-단독 쌍만 센다",
        True,
    ),
    m(
        "Q10-unsignaled-counts-the-confirmed",
        RR,
        _RR_UNSIGNALED,
        "label_only_pair_stmt.where(pair_stats.c.has_signal.is_(True))",
        "신호 없는 쌍 = 학생 신호 공급이 하나도 없는 쌍",
        True,
    ),
]

_TOUCHED = (HD, ENG, MOD, EDC, COACH, CFG, RR)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다."""
    for target in _TOUCHED:
        for cached in (target.parent / "__pycache__").glob(f"{target.stem}.*.pyc"):
            cached.unlink()


def run_pytest(*, integration: bool) -> tuple[int, str, str]:
    """대상 표면을 돌리고 `(종료 코드, 첫 실패 줄, 요약 줄)`을 돌려준다.

    판정은 종료 코드로만 한다. 첫 실패 줄은 **보고용**이다 — RED가 "가드가 그 상태를 잡아서"인지
    "주입이 임포트·구문을 깨서"인지 사람이 눈으로 구별하게 한다(후자는 위장 검출이다).
    **요약 줄**은 `skipped` 검사용이다 — 통합 표면은 DB에 닿지 못하면 건너뛰고 종료 코드 0을
    내므로(DB 이름 대소문자 접힘으로 실측), 종료 코드만으로는 '통과'와 '돌지 않음'이 같은 화면이다.
    """
    drop_bytecode()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    targets = UNIT_TESTS
    if integration:
        env.update(WHYMATH_RUN_INTEGRATION="1", WHYMATH_DB_DISABLE_POOL="1")
        targets = INTEGRATION_TESTS
    args = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "pyproject.toml",
        "--rootdir=.",
        "-q",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        "-x",
        *targets,
    ]
    # HARN-19: 서브프로세스 출력 디코딩은 인코딩을 명시한다. 매달리는 뮤테이션은 원복을 건너뛰게
    # 하므로 시간 상한을 건다.
    proc = subprocess.run(
        args,
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1500,
    )
    failure = next(
        (line for line in proc.stdout.splitlines() if line.startswith(("FAILED ", "ERROR "))), ""
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    return proc.returncode, failure, summary


def apply_mutation(mutation: Mutation) -> None:
    """치환 + **적용 실재 단언** — 앵커 1건·결과가 원본과 다름을 쓰기 전에 확인한다."""
    src = mutation.path.read_text(encoding="utf-8")
    mutated = src
    for old, new in mutation.edits:
        count = mutated.count(old)
        if count != 1:
            raise AssertionError(
                f"{mutation.name}: 앵커 {count}건(1건이어야 한다) — 하네스가 대상을 놓쳤다"
            )
        replaced = mutated.replace(old, new)
        if old != new and replaced == mutated:
            raise AssertionError(f"{mutation.name}: 치환이 들어가지 않았다")
        mutated = replaced
    if mutated == src:
        raise AssertionError(f"{mutation.name}: 치환 후에도 원본과 동일 — 주입이 들어가지 않았다")
    mutation.path.write_text(mutated, encoding="utf-8")
    if mutation.path.read_text(encoding="utf-8") != mutated:
        raise AssertionError(f"{mutation.name}: 쓴 내용이 다시 읽히지 않는다")
    compile(mutated, str(mutation.path), "exec")  # 구문을 깨면 '검출'이 아니라 하네스 결함이다


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="이름에 이 문자열이 든 뮤테이션만 실행")
    parser.add_argument(
        "--with-integration",
        action="store_true",
        help="서빙 경로(실 PG) 뮤테이션도 돌린다 — WHYMATH_DATABASE_URL 필요",
    )
    args = parser.parse_args()

    if args.with_integration and not os.environ.get("WHYMATH_DATABASE_URL"):
        print("✗ --with-integration에는 WHYMATH_DATABASE_URL(마이그레이션 적용된 DB)이 필요하다")
        return 1
    selected = [
        mu
        for mu in MUTATIONS
        if (args.with_integration or not mu.integration) and (not args.only or args.only in mu.name)
    ]
    if not selected:
        print("✗ 선택된 뮤테이션이 0건이다 — 이름 조각을 확인하라(빈 실행은 통과가 아니다)")
        return 1
    names = [mu.name for mu in MUTATIONS]
    if len(set(names)) != len(names):
        print("✗ 뮤테이션 이름이 중복이다 — 하네스 결함")
        return 1
    surfaces = sorted({mu.integration for mu in selected})
    before = {path: sha256(path) for path in _TOUCHED}

    # ── 성공 방향 대조군 — 무주입이 GREEN이어야 이후 RED가 의미를 가진다 ──
    for integration in surfaces:
        baseline, _, summary = run_pytest(integration=integration)
        label = "서빙 경로" if integration else "단위"
        print(f"[대조군:{label}] 무주입 exit={baseline} ({'GREEN' if baseline == 0 else 'RED'})")
        if baseline == 0 and ("skipped" in summary or "passed" not in summary):
            print(f"✗ 대조군이 돌지 않았다(건너뜀) — {summary!r}. DB 이름·URL을 확인하라(소문자)")
            return 1
        if baseline != 0:
            print("✗ 대조군이 이미 RED다 — 이 상태에서는 어떤 뮤테이션도 '검출'로 계상할 수 없다")
            return 1

    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        backups: dict[Path, Path] = {}
        for path in {mu.path for mu in selected}:
            backup = Path(tmp) / f"{path.parent.name}__{path.name}"
            shutil.copy2(path, backup)  # git이 아니라 파일 복사로 원복한다(2026-08-10 규율)
            backups[path] = backup

        def restore_all() -> None:
            """어떤 종료 경로에서도 원복한다 — 중단(시그널)은 `finally`를 건너뛴다."""
            for src_path, backup_path in backups.items():
                if backup_path.exists():
                    shutil.copy2(backup_path, src_path)

        atexit.register(restore_all)

        def _on_signal(signum: int, _frame: FrameType | None) -> None:
            restore_all()
            raise SystemExit(128 + signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _on_signal)

        for mu in selected:
            try:
                apply_mutation(mu)
                code, failure, summary = run_pytest(integration=mu.integration)
                if code == 0 and "skipped" in summary:
                    failure = f"무효: 뮤테이션 실행이 건너뜀 — {summary}"
                detected = code != 0
                mark = "RED(검출)" if detected else "GREEN(생존)"
                surface = "서빙" if mu.integration else "단위"
                print(f"  {mu.name:<46} [{surface}] axis={mu.axis:<34} exit={code} {mark}")
                if failure:
                    print(f"      ↳ {failure[:150]}")
                if not detected:
                    survivors.append(mu.name)
            finally:
                shutil.copy2(backups[mu.path], mu.path)
                if mu.path.read_bytes() != backups[mu.path].read_bytes():
                    raise AssertionError(f"{mu.name}: 원복이 바이트 동일하지 않다 — 중단")

    after = {path: sha256(path) for path in _TOUCHED}
    if before != after:
        changed = [p.name for p in _TOUCHED if before[p] != after[p]]
        print(f"✗ 실행 전후 sha256이 다르다: {changed} — 작업 트리가 실행 전과 같지 않다")
        return 1
    print(f"\n원복 확인: {len(_TOUCHED)}개 파일 sha256이 실행 전과 동일")
    if survivors:
        print(f"✗ 생존 {len(survivors)}/{len(selected)}: {', '.join(survivors)}")
        print("  생존한 뮤테이션은 '가드가 그 상태를 막지 못한다'는 뜻이다 — 보호로 계상 불가.")
        return 1
    print(f"✓ 전건 검출 {len(selected)}/{len(selected)} — 각 가드가 실제로 그 상태를 막는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
