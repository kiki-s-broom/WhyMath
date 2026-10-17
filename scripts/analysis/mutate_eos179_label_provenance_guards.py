#!/usr/bin/env python3
"""EOS-179 라벨 출처·증거 수 계측과 예측 타당도 리더의 **결함 주입 검증** — 주입해 RED를 본다.

대상은 EOS-179가 만든 다섯 곳이다(태스크 `EOS-179-coach-label-predictive-validity-reader`):

- `l2/mastery_tracking.py` — 증거 수 리더(`get_current_mastery_sample_size`): NULL=모름·0과 구별
- `api/coach.py` — 라벨 출처 판정(`_label_provenance`)·증거 수 조회 조건
  (`_server_mastery_evidence_for`)·결정에 싣는 지점·원장 적재·두 영속 핸들러의 결선
- `l4/models.py` — 두 계측 필드가 응답 본문으로 새지 않게 하는 `exclude`
- `schema/event_data_contract.py` — 원장 필드의 범위
- `ops/recommendation_reach_report.py` — §8 리더: 첫-행 창·신호 경계·분류 불가·라벨 없음·
  증거 수 하한·Wilson 경계·서버 보기·CLI 전달

규율은 선례 `scripts/analysis/mutate_eos178_label_free_guards.py`와 같다 — 주입 실재 단언(앵커 1건 ·
치환 후 원본과 다름 · 쓴 내용 재확인 · 구문 검사) · 순수 Python 치환(셸 heredoc 주입 0) · 백업
**복사** 원복(git 원복 금지)과 바이트 동일성 단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 ·
판정은 pytest 종료 코드 · `skipped`가 든 실행은 무효 · 실행마다 대상 모듈의 바이트코드 캐시 삭제와
`PYTHONDONTWRITEBYTECODE=1` · 실행 전후 sha256 대조.

**각 뮤테이션은 서로 다른 절을 깬다** — "이 절이 없으면 어떤 입력이 통과하는가"에 답하는 반례가
테스트 픽스처에 있어야 그 뮤테이션이 RED가 된다. 같은 종류가 일부만 RED면 하네스를 의심한다.

표면이 둘이다:

- **단위**(기본): 진리표 · 결정 운반 · 직렬화 제외 · 증거 수 조회 조건 · AST 결선 · 계약 범위 ·
  리포트 순수 집계 · Wilson · 렌더·JSON·CLI · ⑱ 쿼리 구조(컴파일 SQL).
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP + 합성 원장 통합
  `tests/backend/api/test_eos179_label_provenance_integration.py`. 환경변수 `WHYMATH_DATABASE_URL`
  (asyncpg URL · **이 브랜치의 head까지 마이그레이션된 DB**)이 필요하다. 창 함수·`bool_or`·
  `bool_and`·JSONB 키 캐스팅의 *의미*는 이 표면에서만 잡힌다(가짜 세션은 쿼리를 무시한다).

사용:
    python3 scripts/analysis/mutate_eos179_label_provenance_guards.py \
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

MT = PKG / "l2" / "mastery_tracking.py"
MOD = PKG / "l4" / "models.py"
EDC = PKG / "schema" / "event_data_contract.py"
COACH = PKG / "api" / "coach.py"
RR = PKG / "ops" / "recommendation_reach_report.py"

UNIT_TESTS = [
    "../../tests/backend/api/test_eos179_label_provenance.py",
    "../../tests/backend/ops/test_recommendation_reach_report.py",
    "../../tests/backend/schema/test_event_data_contract.py",
    "../../tests/backend/l2/test_mastery_tracking.py",
]
INTEGRATION_TESTS = ["../../tests/backend/api/test_eos179_label_provenance_integration.py"]


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


# ── 앵커(원문 그대로 — 각각 1건이어야 한다) ──────────────────────────────────────────
_MT_SIZE = (
    "    return int(row.sample_size) if row is not None and row.sample_size is not None else None\n"
)

_CO_LEVEL_NONE = "    if level is None:\n        return None, None\n"
_CO_EXPLICIT = '    if explicit_level is not None:\n        return "explicit", None\n'
_CO_SERVER_BKT = (
    "    if server_mastery is not None:\n"
    '        return "server_bkt", server_evidence_n\n'
    "    if client_bkt is not None:\n"
    '        return "client_bkt", None\n'
)
_CO_CLIENT_BKT = '    if client_bkt is not None:\n        return "client_bkt", None\n'
_CO_THETA = '    return "server_theta", None\n'
_CO_PAYLOAD_EVID = "        server_evidence_n=server_mastery_evidence,\n"
_CO_PAYLOAD_COPY = (
    '        update={"label_source": label_source, "label_evidence_n": label_evidence_n}\n'
)
_CO_SKIP = "    if server_mastery is None or explicit_level is not None or problem_id is None:\n"
_CO_SIZE_CALL = "    return await get_current_mastery_sample_size(session, user_id, concept_id)\n"
_CO_LOG_SOURCE = "            label_source=label_source,\n"
_CO_LOG_EVID = "            label_evidence_n=label_evidence_n,\n"

_CREATE_EVID = (
    "        body.problem_id,\n"
    "        server_mastery=server_mastery,\n"
    "        explicit_level=body.mastery_level,\n"
)
_APPEND_EVID = (
    "        dialogue.problem_id,\n"
    "        server_mastery=server_mastery,\n"
    "        explicit_level=body.mastery_level,\n"
)
_CREATE_PAYLOAD = (
    "            problem_id=body.problem_id,\n"
    "            expected_answer=expected_answer,\n"
    "            server_mastery=server_mastery,\n"
    "            server_theta=server_theta,\n"
    "            server_mastery_evidence=server_mastery_evidence,\n"
)
_APPEND_PAYLOAD = (
    "            problem_id=dialogue.problem_id,\n"
    "            expected_answer=expected_answer,\n"
    "            server_mastery=server_mastery,\n"
    "            server_theta=server_theta,\n"
    "            server_mastery_evidence=server_mastery_evidence,\n"
)
_LOG_TAIL = (
    "        base_hint_level=decision.base_hint_level,\n"
    "        ability_level=decision.applied_mastery_level,\n"
    "        label_source=decision.label_source,\n"
    "        label_evidence_n=decision.label_evidence_n,\n"
)
_LOG_HEAD_CREATE = (
    "        problem_id=body.problem_id,\n"
    "        attempt_id=dialogue.attempt_id,\n"
    "        hint_level=decision.hint_level,\n"
    "        mode=body.mode,\n"
    "        persona=event_persona,\n"
    "        client_state_mismatch=bool(mismatch_fields),\n"
    "        turn_handled=completion.handled,\n"
    "        served_hint=served_hint,\n"
)
_LOG_HEAD_APPEND = _LOG_HEAD_CREATE.replace("body.problem_id", "dialogue.problem_id")
_LOG_NO_SOURCE = (
    "        base_hint_level=decision.base_hint_level,\n"
    "        ability_level=decision.applied_mastery_level,\n"
    "        label_evidence_n=decision.label_evidence_n,\n"
)
_LOG_NO_EVID = (
    "        base_hint_level=decision.base_hint_level,\n"
    "        ability_level=decision.applied_mastery_level,\n"
    "        label_source=decision.label_source,\n"
)

_MOD_SOURCE = (
    "    label_source: str | None = Field(\n        default=None,\n        exclude=True,\n"
)
_MOD_EVID = (
    "    label_evidence_n: int | None = Field(\n        default=None,\n        exclude=True,\n"
)
_EDC_EVID_GE = "    label_evidence_n: int | None = Field(\n        default=None,\n        ge=0,\n"
_EDC_SOURCE_MAX = (
    "    label_source: str | None = Field(\n        default=None,\n        max_length=16,\n"
)

_RR_RANK = "        .where(ranked.c.rn == 1)\n"
_RR_ORDER = "            .over(partition_by=part, order_by=AttemptEvent.event_at.asc())\n"
_RR_PART = "    part = (AttemptEvent.user_id, AttemptEvent.problem_id)\n"
_RR_SIGNAL = '            func.bool_or(base >= 2).over(partition_by=part).label("has_signal"),\n'
_RR_CLASSIFIED = (
    "            func.bool_and(base.isnot(None)).over(partition_by=part)"
    '.label("all_classified"),\n'
)
_RR_TYPE = "        .where(AttemptEvent.event_type == EventType.힌트제공)\n        .subquery()\n"
_RR_NULLIF = '            func.nullif(level, "").label("label"),\n'
_RR_UNLABELED = "        if label is None:\n            unlabeled += int(pairs)\n"
_RR_UNCLASSIFIED = "        elif all_classified is not True:\n"
_RR_FLOOR = "        stmt = stmt.where(ranked.c.evidence_n >= min_evidence_n)\n"
_RR_SORT = '        cells=tuple(sorted(cells, key=lambda c: (c[0], c[1] or ""))),\n'
_RR_ZERO = "    if denominator == 0:\n        return WilsonRate(numerator, 0, None, None, None)\n"
_RR_WILSON = (
    "        wilson_lower_bound(numerator, denominator),\n"
    "        wilson_upper_bound(numerator, denominator),\n"
)
_RR_RECALL = "        novice_recall=_wilson_rate(novice_signals, signal_total),\n"
_RR_OTHER = (
    "        other_signal_rate=_wilson_rate("
    "signal_total - novice_signals, pair_total - novice_pairs),\n"
)
_RR_SERVER_SET = '_SERVER_LABEL_SOURCES = frozenset({"server_bkt", "server_theta"})\n'
_RR_SOURCE_FILTER = (
    "        if sources is not None and source not in sources:\n            continue\n"
)
_RR_UNFAMILIAR = (
    "    labels = list(_LABEL_ORDER) + sorted(k for k in pairs if k not in _LABEL_ORDER)\n"
)
_RR_SRC_UNKNOWN = "            c[2] for c in counts.coach_label_validity_cells if c[1] is None\n"
_RR_FETCH_FLOOR = (
    "    validity = await fetch_label_validity(session, min_evidence_n=min_label_evidence_n)\n"
)
_RR_RECORD_FLOOR = "        coach_label_min_evidence_n=min_label_evidence_n,\n"
_RR_CLI = "        report = asyncio.run(_run(args.min_label_evidence_n))\n"
_RR_RENDER_BOUNDS = '        f"(Wilson 단측 95% 하한 {r.lower95:.1%} · 상한 {r.upper95:.1%})"\n'


MUTATIONS: list[Mutation] = [
    # ── L2 증거 수 리더 ────────────────────────────────────────────────────────
    m(
        "L01-unknown-folds-into-zero",
        MT,
        _MT_SIZE,
        "    return int(row.sample_size) if row is not None and row.sample_size is not None"
        " else 0\n",
        "NULL·이력 없음 = 모름(0 아님)",
    ),
    m(
        "L02-off-by-one-count",
        MT,
        _MT_SIZE,
        "    return int(row.sample_size) + 1 if row is not None and row.sample_size is not None"
        " else None\n",
        "증거 수 = 최신 행의 sample_size 그대로",
    ),
    # ── 라벨 출처 판정 ─────────────────────────────────────────────────────────
    m(
        "C01-no-label-still-claims-a-source",
        COACH,
        _CO_LEVEL_NONE,
        "    if level is None:\n        pass\n",
        "라벨 없음 → 출처·증거 수도 없음(날조 금지)",
    ),
    m(
        "C02-explicit-label-loses-its-source",
        COACH,
        _CO_EXPLICIT,
        '    if False:\n        return "explicit", None\n',
        "명시 라벨은 모든 입력을 이긴다",
    ),
    m(
        "C03-server-source-drops-the-count",
        COACH,
        '        return "server_bkt", server_evidence_n\n',
        '        return "server_bkt", None\n',
        "서버 숙달도 라벨은 증거 수를 싣는다",
    ),
    m(
        "C04-client-bkt-borrows-a-stray-count",
        COACH,
        _CO_CLIENT_BKT,
        '    if client_bkt is not None:\n        return "client_bkt", server_evidence_n\n',
        "클라 bkt 라벨의 증거로 서버 숙달도의 관측 수를 적지 않는다",
    ),
    m(
        "C05-client-checked-before-server",
        COACH,
        _CO_SERVER_BKT,
        "    if client_bkt is not None:\n"
        '        return "client_bkt", None\n'
        "    if server_mastery is not None:\n"
        '        return "server_bkt", server_evidence_n\n',
        "서버 값이 클라 값을 대체한다(출처 우선순위)",
    ),
    m(
        "C06-theta-only-labelled-as-client",
        COACH,
        _CO_THETA,
        '    return "client_bkt", None\n',
        "숙달도 없이 θ뿐인 라벨의 출처",
    ),
    # ── 결정에 싣는 지점 ───────────────────────────────────────────────────────
    m(
        "C07-decision-ignores-the-lookup",
        COACH,
        _CO_PAYLOAD_EVID,
        "        server_evidence_n=None,\n",
        "조회한 증거 수가 결정까지 운반된다",
    ),
    m(
        "C08-decision-drops-the-count",
        COACH,
        _CO_PAYLOAD_COPY,
        '        update={"label_source": label_source, "label_evidence_n": None}\n',
        "결정이 증거 수를 싣는다",
    ),
    # ── 증거 수 조회 조건(불필요한 조회 0) ───────────────────────────────────────
    m(
        "C09-lookup-runs-when-explicit-wins",
        COACH,
        _CO_SKIP,
        "    if server_mastery is None or problem_id is None:\n",
        "명시 라벨이 이긴 턴은 증거 수를 조회하지 않는다",
    ),
    m(
        "C10-lookup-runs-without-server-mastery",
        COACH,
        _CO_SKIP,
        "    if explicit_level is not None or problem_id is None:\n",
        "서버 숙달도가 안 쓰인 턴은 조회하지 않는다",
    ),
    m(
        "C11-lookup-runs-without-a-problem",
        COACH,
        _CO_SKIP,
        "    if server_mastery is None or explicit_level is not None:\n",
        "문항 맥락이 없으면 조회하지 않는다",
    ),
    m(
        "C12-lookup-reads-the-wrong-key",
        COACH,
        _CO_SIZE_CALL,
        "    return await get_current_mastery_sample_size(session, user_id, problem_id)\n",
        "증거 수는 문항이 아니라 개념의 측정 행에서 읽는다",
        True,
    ),
    # ── 원장 적재 ──────────────────────────────────────────────────────────────
    m(
        "C13-ledger-writes-no-source",
        COACH,
        _CO_LOG_SOURCE,
        "            label_source=None,\n",
        "원장 행이 label_source를 싣는다",
    ),
    m(
        "C14-ledger-writes-no-count",
        COACH,
        _CO_LOG_EVID,
        "            label_evidence_n=None,\n",
        "원장 행이 label_evidence_n을 싣는다",
    ),
    # ── 두 영속 핸들러의 결선(AST) ─────────────────────────────────────────────
    m(
        "C15-create-skips-the-lookup-flag",
        COACH,
        _CREATE_EVID,
        "        body.problem_id,\n        server_mastery=server_mastery,\n",
        "세션 생성 핸들러가 명시 라벨 여부를 조회에 넘긴다",
    ),
    m(
        "C16-append-skips-the-lookup-flag",
        COACH,
        _APPEND_EVID,
        "        dialogue.problem_id,\n        server_mastery=server_mastery,\n",
        "턴 추가 핸들러가 명시 라벨 여부를 조회에 넘긴다",
    ),
    m(
        "C17-create-drops-the-count-from-the-decision",
        COACH,
        _CREATE_PAYLOAD,
        _CREATE_PAYLOAD.replace(
            "            server_mastery_evidence=server_mastery_evidence,\n", ""
        ),
        "세션 생성 핸들러가 증거 수를 결정에 넘긴다",
    ),
    m(
        "C18-append-drops-the-count-from-the-decision",
        COACH,
        _APPEND_PAYLOAD,
        _APPEND_PAYLOAD.replace(
            "            server_mastery_evidence=server_mastery_evidence,\n", ""
        ),
        "턴 추가 핸들러가 증거 수를 결정에 넘긴다",
    ),
    m(
        "C19-create-ledger-drops-the-source",
        COACH,
        _LOG_HEAD_CREATE + _LOG_TAIL,
        _LOG_HEAD_CREATE + _LOG_NO_SOURCE,
        "세션 생성 핸들러의 원장 적재가 출처를 싣는다",
    ),
    m(
        "C20-append-ledger-drops-the-source",
        COACH,
        _LOG_HEAD_APPEND + _LOG_TAIL,
        _LOG_HEAD_APPEND + _LOG_NO_SOURCE,
        "턴 추가 핸들러의 원장 적재가 출처를 싣는다",
    ),
    m(
        "C21-create-ledger-drops-the-count",
        COACH,
        _LOG_HEAD_CREATE + _LOG_TAIL,
        _LOG_HEAD_CREATE + _LOG_NO_EVID,
        "세션 생성 핸들러의 원장 적재가 증거 수를 싣는다",
    ),
    m(
        "C22-append-ledger-drops-the-count",
        COACH,
        _LOG_HEAD_APPEND + _LOG_TAIL,
        _LOG_HEAD_APPEND + _LOG_NO_EVID,
        "턴 추가 핸들러의 원장 적재가 증거 수를 싣는다",
    ),
    # ── 응답 본문 비노출 · 계약 범위 ────────────────────────────────────────────
    m(
        "M01-source-leaks-into-the-response",
        MOD,
        _MOD_SOURCE,
        "    label_source: str | None = Field(\n        default=None,\n        exclude=False,\n",
        "label_source는 응답 본문에 나가지 않는다",
    ),
    m(
        "M02-count-leaks-into-the-response",
        MOD,
        _MOD_EVID,
        "    label_evidence_n: int | None = Field(\n"
        "        default=None,\n        exclude=False,\n",
        "label_evidence_n은 응답 본문에 나가지 않는다",
    ),
    m(
        "E01-contract-accepts-a-negative-count",
        EDC,
        _EDC_EVID_GE,
        "    label_evidence_n: int | None = Field(\n        default=None,\n",
        "원장 계약: 증거 수는 0 이상",
    ),
    m(
        "E02-contract-source-length-too-short",
        EDC,
        _EDC_SOURCE_MAX,
        "    label_source: str | None = Field(\n        default=None,\n        max_length=4,\n",
        "원장 계약: 출처 문자열 범위",
    ),
    # ── §8 리더: ⑱ 쿼리 ─────────────────────────────────────────────────────────
    m(
        "R01-first-row-becomes-every-row",
        RR,
        _RR_RANK,
        "        .where(ranked.c.rn >= 1)\n",
        "쌍의 *첫* 공급 행 라벨만 쓴다",
    ),
    m(
        "R02-last-row-instead-of-first",
        RR,
        _RR_ORDER,
        "            .over(partition_by=part, order_by=AttemptEvent.event_at.desc())\n",
        "첫 행 = 시각 오름차순 1번",
        True,
    ),
    m(
        "R03-pair-partition-loses-the-problem",
        RR,
        _RR_PART,
        "    part = (AttemptEvent.user_id,)\n",
        "쌍 = (학생, 문항)",
    ),
    m(
        "R04-signal-boundary-off-by-one",
        RR,
        _RR_SIGNAL,
        '            func.bool_or(base > 2).over(partition_by=part).label("has_signal"),\n',
        "학생 신호 경계(base_level >= 2)",
        True,
    ),
    m(
        "R05-unclassified-folds-into-no-signal",
        RR,
        _RR_CLASSIFIED,
        "            func.bool_or(base.isnot(None)).over(partition_by=part)"
        '.label("all_classified"),\n',
        "구판 행이 섞인 쌍은 신호 판정 불가(신호 없음으로 접지 않는다)",
        True,
    ),
    m(
        "R06-reads-other-event-types",
        RR,
        _RR_TYPE,
        "        .subquery()\n",
        "공급 원장(힌트제공)만 본다",
        True,
    ),
    m(
        "R07-empty-label-counts-as-a-label",
        RR,
        _RR_NULLIF,
        '            level.label("label"),\n',
        "빈 문자열 라벨 = 라벨 없음",
        True,
    ),
    m(
        "R08-evidence-floor-off-by-one",
        RR,
        _RR_FLOOR,
        "        stmt = stmt.where(ranked.c.evidence_n > min_evidence_n)\n",
        "증거 수 하한 K = 첫 행의 n >= K",
    ),
    # ── §8 리더: 행 분류 ────────────────────────────────────────────────────────
    m(
        "R09-unlabeled-pairs-are-not-set-aside",
        RR,
        _RR_UNLABELED,
        "        if False:\n            unlabeled += int(pairs)\n",
        "첫 행에 라벨 없는 쌍은 따로 센다",
    ),
    m(
        "R10-unknown-classification-counts-as-classified",
        RR,
        _RR_UNCLASSIFIED,
        "        elif all_classified is False:\n",
        "분류 가능 여부가 NULL이어도 신호 판정 가능으로 접지 않는다",
    ),
    m(
        "R11-cells-keep-the-query-order",
        RR,
        _RR_SORT,
        "        cells=tuple(cells),\n",
        "칸은 (라벨, 출처)로 정렬해 쿼리 반환 순서에 기대지 않는다",
    ),
    # ── §8 순수 집계 · Wilson ───────────────────────────────────────────────────
    m(
        "R12-zero-denominator-is-computed",
        RR,
        _RR_ZERO,
        "    if denominator < 0:\n        return WilsonRate(numerator, 0, None, None, None)\n",
        "분모 0 → 비율·경계 None(0과 구별)",
    ),
    m(
        "R13-wilson-bounds-swapped",
        RR,
        _RR_WILSON,
        "        wilson_upper_bound(numerator, denominator),\n"
        "        wilson_lower_bound(numerator, denominator),\n",
        "Wilson 하한·상한이 제 자리",
    ),
    m(
        "R14-recall-denominator-is-all-pairs",
        RR,
        _RR_RECALL,
        "        novice_recall=_wilson_rate(novice_signals, pair_total),\n",
        "'초보' 재현율의 분모 = 신호 쌍",
    ),
    m(
        "R15-contrast-includes-the-novice",
        RR,
        _RR_OTHER,
        "        other_signal_rate=_wilson_rate(signal_total, pair_total),\n",
        "대조 = '초보' 아닌 라벨의 신호율",
    ),
    m(
        "R16-server-view-admits-client-labels",
        RR,
        _RR_SERVER_SET,
        '_SERVER_LABEL_SOURCES = frozenset({"server_bkt", "server_theta", "client_bkt"})\n',
        "서버 보기 = 서버가 만든 라벨만",
    ),
    m(
        "R17-server-view-has-no-source-filter",
        RR,
        _RR_SOURCE_FILTER,
        "        if False:\n            continue\n",
        "보기별 출처 필터",
    ),
    m(
        "R18-unfamiliar-labels-are-dropped",
        RR,
        _RR_UNFAMILIAR,
        "    labels = list(_LABEL_ORDER)\n",
        "원장에만 있는 라벨을 버리지 않는다",
    ),
    m(
        "R19-source-unknown-counts-the-known",
        RR,
        _RR_SRC_UNKNOWN,
        "            c[2] for c in counts.coach_label_validity_cells if c[1] is not None\n",
        "출처 미기록 쌍 수",
    ),
    # ── 전달 · 표시 ─────────────────────────────────────────────────────────────
    m(
        "R20-floor-is-recorded-but-not-applied",
        RR,
        _RR_FETCH_FLOOR,
        "    validity = await fetch_label_validity(session)\n",
        "하한이 ⑱ 쿼리에 실제로 걸린다",
    ),
    m(
        "R21-floor-is-applied-but-not-recorded",
        RR,
        _RR_RECORD_FLOOR,
        "        coach_label_min_evidence_n=None,\n",
        "적용한 하한이 리포트에 남는다",
    ),
    m(
        "R22-cli-floor-not-forwarded",
        RR,
        _RR_CLI,
        "        report = asyncio.run(_run())\n",
        "CLI 플래그가 실행까지 전달된다",
    ),
    m(
        "R23-rendered-bounds-swapped",
        RR,
        _RR_RENDER_BOUNDS,
        '        f"(Wilson 단측 95% 하한 {r.upper95:.1%} · 상한 {r.lower95:.1%})"\n',
        "렌더가 하한·상한을 제 자리에 찍는다",
    ),
]

_TOUCHED = (MT, MOD, EDC, COACH, RR)


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
