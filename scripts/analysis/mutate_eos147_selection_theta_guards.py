#!/usr/bin/env python3
"""EOS-147 선택 θ 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 "전부 정답 이력의 추천 표적 θ를 추정 θ에서 분리한다"는 결정(판정문
`docs/reviews/eos147_all_correct_theta_pin_judgment_2026-09-29.md`)이 만든 다섯 곳이다:
`l2/irt.py`(경계 판정·표적 규칙·상수) · `l2/next_problem_selection.py`(상태 객체·로더 — 특히
**SE가 계속 추정 θ에서 계산되는가**) · `l2/recommendation_policy.py`·
`api/_next_problem_policy.py`(두 정책의 θ 소비 **지점마다**) ·
`l2/recommendation_evidence.py`(처치 기록 키 `selection_theta`·`theta_boundary` · 정책 버전 식별자
4종) · `api/me.py`(응답 매핑·처치 기록 전달 — 서빙 경로 표면). 추정기 자신(`estimate_ability`)을
흔들면 동결 테스트가 RED가 되는지도 잰다(불변 열). 단계 상수는 0.5(잠정 — 처음 1.0이었다가 독립
비판을 받고 내렸다)이고, 옛 값 1.0으로 되돌린 뮤테이션(`I03`)이 새 리터럴·사다리 동결 테스트에서
RED가 되어야 한다.

규율은 선례 `scripts/analysis/mutate_eos26_r6_guards.py`와 같다 — 주입 실재 단언(앵커 1건 ·
치환 후 원본과 다름 · 쓴 내용 재확인) · 순수 Python 치환(셸 heredoc 주입 0) · 백업 **복사**
원복(git 원복 금지)과 바이트 동일성 단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은
pytest 종료 코드 · 실행마다 대상 모듈의 바이트코드 캐시 삭제와 `PYTHONDONTWRITEBYTECODE=1`.
여기에 더해 **실행 전후 sha256을 대조**해 작업 트리가 실행 전과 같은 바이트로 돌아왔음을
마지막에 다시 단언한다.

**같은 종류가 일부만 RED면 하네스를 의심한다** — 정책 지점별 뮤테이션(`P05`~`P10` ·
`S05`~`S08`) · 정책 버전 리터럴(`V01`~`V04`) · 처치 기록의 경계 키(`E05`~`E07`)는 각각 같은
종류이므로 전건이 RED여야 한다. 하나라도 생존하면 그 지점을 재는 테스트가 없다는 뜻이다.

표면이 둘이다(뮤테이션 총 58종 — 단위 52종 + 서빙 경로 6종):

- **단위**(기본): `tests/backend/l2/test_eos147_selection_theta.py` ·
  `tests/backend/api/test_eos147_selection_theta_suneung.py` — DB 없이 규칙·상태 객체·정책 소비
  지점·사다리 순서·처치 기록 키·버전 리터럴.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP 통합 테스트
  `tests/backend/api/test_eos147_all_correct_selection_theta.py`. 환경변수
  `WHYMATH_DATABASE_URL`(asyncpg URL · **이 브랜치의 head까지 마이그레이션된 DB**)이 필요하다.
  `api/me.py` 응답 매핑·처치 기록 전달(`M01`~`M04`)처럼 단위가 못 보는 지점은 이 표면에서만 잡힌다.

사용: `python3 scripts/analysis/mutate_eos147_selection_theta_guards.py
[--with-integration] [--only 이름조각]`
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

IRT = PKG / "l2" / "irt.py"
NPS = PKG / "l2" / "next_problem_selection.py"
POLICY = PKG / "l2" / "recommendation_policy.py"
SUNEUNG = PKG / "api" / "_next_problem_policy.py"
EVIDENCE = PKG / "l2" / "recommendation_evidence.py"
ME = PKG / "api" / "me.py"

UNIT_TESTS = [
    "../../tests/backend/l2/test_eos147_selection_theta.py",
    "../../tests/backend/api/test_eos147_selection_theta_suneung.py",
]
INTEGRATION_TESTS = ["../../tests/backend/api/test_eos147_all_correct_selection_theta.py"]


@dataclass(frozen=True)
class Mutation:
    """뮤테이션 1건 — 어느 파일의 어느 절을 무엇으로 바꾸는가 + 어느 표면이 RED여야 하는가."""

    name: str
    path: Path
    old: str
    new: str
    axis: str  # 이 뮤테이션이 검사하는 축(보고용)
    integration: bool = False  # True면 실 PG 서빙 경로 표면에서 판정한다


# ── 앵커(원문 그대로 — 1건이어야 한다) ───────────────────────────────────────────────
_STEP = "ALL_CORRECT_STEP_LOGIT = 0.5\n"
_FLOOR_CAP = "    return min(upper, max(cold_start, reach))\n"
_REACH = "    reach = max(item.difficulty for item, _ in responses) + step\n"
_COLD = "    cold_start = estimate_ability([])\n"
_GATE = '    if ability_boundary(responses) != "upper":\n        return estimated_theta\n'
_ALL = (
    "    if not responses:\n        return None\n"
    "    if all(correct for _, correct in responses):\n"
    '        return "upper"\n'
    "    if not any(correct for _, correct in responses):\n"
    '        return "lower"\n'
    "    return None\n"
)
_EST_UPPER = (
    "    if all(correct for _, correct in responses):\n"
    "        return upper\n"
    "    if not any(correct for _, correct in responses):\n"
    "        return lower\n"
)

_PROP = (
    "        return (\n"
    "            self.theta if self.boundary_selection_theta is None"
    " else self.boundary_selection_theta\n"
    "        )\n"
)
_LOAD_SEL = "    selection_theta = ability_for_selection(responses, theta)\n"
_LOAD_SE = "    se = ability_standard_error(theta, administered_items)\n"
_LOAD_BOUNDARY = "        theta_boundary=ability_boundary(responses),\n"
_LOAD_OVERRIDE = (
    "        boundary_selection_theta=selection_theta if selection_theta != theta else None,\n"
)
_LOAD_THETA = "    theta = estimate_ability(responses)\n"

_POL_THETA = "        theta = attempt_state.selection_theta\n"
_POL_COMMON_THETA = '            "theta": attempt_state.theta,\n'
_POL_COMMON_SEL = '            "selection_theta": theta,\n'
_POL_COMMON_BOUNDARY = '            "theta_boundary": attempt_state.theta_boundary,\n'
_POL_POOL = (
    "            else await load_candidate_rows(\n"
    "                session,\n"
    "                theta,\n"
)
_POL_ROUTE = "            learner_state,\n            theta=theta,\n"
_POL_SELECT = "\n        best = select_weighted_item(theta, items, weights=weights)\n"
_POL_SCORES = "            scores=_candidate_scores(theta, candidate_rows, items, weights),\n"
_POL_AXES = (
    "            items=items,\n            theta=theta,\n            sibling_ids=sibling_ids,\n"
    "        )\n        weight_axes_applied"
)
_POL_RESELECT = (
    "                    learning_context=effective_context,\n                    theta=theta,\n"
)

_SUN_THETA = "        theta = attempt_state.selection_theta\n"
_SUN_COMMON_THETA = '            "theta": attempt_state.theta,\n'
_SUN_COMMON_SEL = '            "selection_theta": theta,\n'
_SUN_COMMON_BOUNDARY = '            "theta_boundary": attempt_state.theta_boundary,\n'
_SUN_ORDER = (
    "        stmt = stmt.order_by(*candidate_pool_order_by(theta)).limit(CANDIDATE_POOL_SIZE)\n"
)
_SUN_BAND = "                    learning_band_weight(theta, IrtItem(difficulty=b))\n"
_SUN_INDEX = (
    "        chosen_index = recommend_suneung_index(\n"
    "            theta, candidates, persona, extra_weights=extra_weights\n"
    "        )\n"
)
_SUN_SCORE = (
    "                    item_information(theta, IrtItem(difficulty=b))"
    " * suneung_item_weight(p) * extra,\n"
)

_EVD_GATE = "    if selection_theta is not None and selection_theta != theta:\n"
_EVD_BOUNDARY = (
    "    if theta_boundary is not None:\n"
    "        meta[META_KEY_THETA_BOUNDARY] = theta_boundary\n"
)
_EVD_VER_CAT = 'POLICY_VERSION_CAT: str = "cat_v4"\n'
_EVD_VER_SUNEUNG = 'POLICY_VERSION_SUNEUNG: str = "suneung_v3"\n'
_EVD_VER_REMEDIATION = 'POLICY_VERSION_CAT_STATE_REMEDIATION: str = "cat_v1_state_remediation"\n'
_EVD_VER_UNDIAGNOSED = 'POLICY_VERSION_CAT_STATE_UNDIAGNOSED: str = "cat_v2_state_undiagnosed"\n'
_ME_SEL = (
    "        selection_theta=(\n"
    "            outcome.selection_theta"
    " if outcome.selection_theta is not None else outcome.theta\n"
    "        ),\n"
)
_ME_BOUNDARY = "        ),\n        theta_boundary=outcome.theta_boundary,\n"
_ME_LEDGER = (
    "            selection_theta=outcome.selection_theta,\n"
    "            theta_boundary=outcome.theta_boundary,\n"
    "            pool_size=outcome.candidate_pool_size,\n"
)


def _swap(old: str, a: str, b: str) -> str:
    """`old` 안의 부분 문자열 `a`를 `b`로 — 앵커와 치환본이 한 곳에서만 갈라지게 한다."""
    assert a in old, (a, old)
    return old.replace(a, b, 1)


MUTATIONS: list[Mutation] = [
    # ── 축 1: 단계 상수 — 리터럴 기대값이 상수를 따라 움직이지 않는가 ─────────────────
    Mutation("I01-step-zero", IRT, _STEP, "ALL_CORRECT_STEP_LOGIT = 0.0\n", "단계 상수"),
    Mutation("I02-step-two", IRT, _STEP, "ALL_CORRECT_STEP_LOGIT = 2.0\n", "단계 상수"),
    Mutation("I03-step-old-one", IRT, _STEP, "ALL_CORRECT_STEP_LOGIT = 1.0\n", "단계 상수(옛 값)"),
    # ── 축 2: 표적 규칙의 절 — 바닥·상한·최고 난이도·경계 게이트 ─────────────────────
    Mutation(
        "I04-no-cold-start-floor",
        IRT,
        _FLOOR_CAP,
        "    return min(upper, reach)\n",
        "콜드스타트 바닥",
    ),
    Mutation(
        "I05-no-upper-cap", IRT, _FLOOR_CAP, "    return max(cold_start, reach)\n", "상한 클램프"
    ),
    Mutation(
        "I06-min-instead-of-max",
        IRT,
        _REACH,
        _swap(_REACH, "max(", "min("),
        "맞힌 최고 난이도 앵커",
    ),
    Mutation(
        "I07-rule-applies-to-lower-too",
        IRT,
        _GATE,
        "    if ability_boundary(responses) is None:\n        return estimated_theta\n",
        "하한 비대칭",
    ),
    Mutation(
        "I08-rule-never-applies",
        IRT,
        _GATE,
        "    if True:\n        return estimated_theta\n",
        "규칙 발동",
    ),
    Mutation(
        "I09-estimate-recomputed-not-passed",
        IRT,
        _GATE,
        '    if ability_boundary(responses) != "upper":\n'
        "        return estimate_ability(responses)\n",
        "추정 θ 통과(센티널)",
    ),
    Mutation(
        "I10-cold-start-hardcoded",
        IRT,
        _COLD,
        "    cold_start = 0.5\n",
        "바닥의 유도",
    ),
    # ── 축 3: 경계 판정 ───────────────────────────────────────────────────────────
    Mutation(
        "B01-any-instead-of-all",
        IRT,
        _ALL,
        _swap(_ALL, "if all(correct", "if any(correct"),
        "경계 판정(전부 정답)",
    ),
    Mutation(
        "B02-upper-lower-swapped",
        IRT,
        _ALL,
        _swap(_swap(_ALL, '"upper"', '"@"'), '"lower"', '"upper"').replace('"@"', '"lower"'),
        "경계 종류",
    ),
    Mutation(
        "B03-empty-is-a-boundary",
        IRT,
        _ALL,
        _swap(_ALL, "    if not responses:\n        return None\n", ""),
        "빈 응답",
    ),
    Mutation(
        "B04-mixed-counts-as-lower",
        IRT,
        _ALL,
        _ALL[: -len("    return None\n")] + '    return "lower"\n',
        "혼합 이력",
    ),
    # ── 축 4: 추정기 자신 — 바뀌지 않는 열(판정문 §2) ────────────────────────────────
    Mutation(
        "X01-estimator-upper-moved",
        IRT,
        _EST_UPPER,
        _swap(_EST_UPPER, "return upper\n", "return upper - 1.0\n"),
        "추정기 불변(상한)",
    ),
    Mutation(
        "X02-estimator-lower-moved",
        IRT,
        _EST_UPPER,
        _swap(_EST_UPPER, "return lower\n", "return lower + 1.0\n"),
        "추정기 불변(하한)",
    ),
    # ── 축 5: 상태 객체·로더 ───────────────────────────────────────────────────────
    Mutation(
        "N01-selection-property-ignores-override",
        NPS,
        _PROP,
        "        return self.theta\n",
        "선택 θ 속성",
    ),
    Mutation(
        "N02-selection-property-truthiness",
        NPS,
        _PROP,
        "        return self.boundary_selection_theta or self.theta\n",
        "0.0 덮어쓰기 값",
    ),
    Mutation(
        "N03-loader-selection-is-estimate",
        NPS,
        _LOAD_SEL,
        "    selection_theta = theta\n",
        "로더가 표적을 내는가",
    ),
    Mutation(
        "N04-loader-drops-boundary",
        NPS,
        _LOAD_BOUNDARY,
        "        theta_boundary=None,\n",
        "로더 경계 사실",
    ),
    Mutation(
        "N05-se-computed-at-selection-theta",
        NPS,
        _LOAD_SE,
        "    se = ability_standard_error(selection_theta, administered_items)\n",
        "SE는 추정 θ에서(위조 금지)",
    ),
    Mutation(
        "N06-estimate-replaced-by-selection",
        NPS,
        _LOAD_THETA,
        "    theta = ability_for_selection(responses, estimate_ability(responses))\n",
        "추정 θ 불변(로더)",
    ),
    Mutation(
        "N07-override-always-carried",
        NPS,
        _LOAD_OVERRIDE,
        "        boundary_selection_theta=selection_theta,\n",
        "덮어쓰기는 다를 때만",
    ),
    # ── 축 6: 기본 CAT 정책의 θ 소비 지점 — 같은 종류이므로 전건 RED여야 한다 ─────────────
    Mutation(
        "P01-policy-uses-estimate",
        POLICY,
        _POL_THETA,
        "        theta = attempt_state.theta\n",
        "정책 표적(전 지점)",
    ),
    Mutation(
        "P02-response-theta-becomes-selection",
        POLICY,
        _POL_COMMON_THETA,
        '            "theta": theta,\n',
        "응답 theta는 추정 θ",
    ),
    Mutation(
        "P03-selection-field-is-estimate",
        POLICY,
        _POL_COMMON_SEL,
        '            "selection_theta": attempt_state.theta,\n',
        "관측 필드 선택 θ",
    ),
    Mutation(
        "P04-boundary-field-dropped",
        POLICY,
        _POL_COMMON_BOUNDARY,
        '            "theta_boundary": None,\n',
        "관측 필드 경계",
    ),
    Mutation(
        "P05-pool-at-estimate",
        POLICY,
        _POL_POOL,
        _swap(_POL_POOL, "                theta,\n", "                attempt_state.theta,\n"),
        "지점: 후보 풀 조회",
    ),
    Mutation(
        "P06-route-at-estimate",
        POLICY,
        _POL_ROUTE,
        _swap(_POL_ROUTE, "theta=theta,", "theta=attempt_state.theta,"),
        "지점: 상태 머신 이음매",
    ),
    Mutation(
        "P07-select-at-estimate",
        POLICY,
        _POL_SELECT,
        "\n        best = select_weighted_item(attempt_state.theta, items, weights=weights)\n",
        "지점: 정보량 선택",
    ),
    Mutation(
        "P08-scores-at-estimate",
        POLICY,
        _POL_SCORES,
        "            scores=_candidate_scores("
        "attempt_state.theta, candidate_rows, items, weights),\n",
        "지점: 후보 점수",
    ),
    Mutation(
        "P09-band-weights-at-estimate",
        POLICY,
        _POL_AXES,
        _swap(_POL_AXES, "theta=theta,", "theta=attempt_state.theta,"),
        "지점: 학습 밴드 가중",
    ),
    Mutation(
        "P10-reselect-at-estimate",
        POLICY,
        _POL_RESELECT,
        _swap(_POL_RESELECT, "theta=theta,", "theta=attempt_state.theta,"),
        "지점: 정렬 재선택",
    ),
    # ── 축 7: 수능 정책의 θ 소비 지점 ──────────────────────────────────────────────
    Mutation(
        "S01-suneung-uses-estimate",
        SUNEUNG,
        _SUN_THETA,
        "        theta = attempt_state.theta\n",
        "수능 표적(전 지점)",
    ),
    Mutation(
        "S02-response-theta-becomes-selection",
        SUNEUNG,
        _SUN_COMMON_THETA,
        '            "theta": theta,\n',
        "응답 theta는 추정 θ",
    ),
    Mutation(
        "S03-selection-field-is-estimate",
        SUNEUNG,
        _SUN_COMMON_SEL,
        '            "selection_theta": attempt_state.theta,\n',
        "관측 필드 선택 θ",
    ),
    Mutation(
        "S04-boundary-field-dropped",
        SUNEUNG,
        _SUN_COMMON_BOUNDARY,
        '            "theta_boundary": None,\n',
        "관측 필드 경계",
    ),
    Mutation(
        "S05-pool-order-at-estimate",
        SUNEUNG,
        _SUN_ORDER,
        _swap(
            _SUN_ORDER,
            "candidate_pool_order_by(theta)",
            "candidate_pool_order_by(attempt_state.theta)",
        ),
        "지점: 후보 풀 정렬",
    ),
    Mutation(
        "S06-band-at-estimate",
        SUNEUNG,
        _SUN_BAND,
        _swap(
            _SUN_BAND, "learning_band_weight(theta,", "learning_band_weight(attempt_state.theta,"
        ),
        "지점: 학습 밴드 가중",
    ),
    Mutation(
        "S07-index-at-estimate",
        SUNEUNG,
        _SUN_INDEX,
        _swap(
            _SUN_INDEX,
            "            theta, candidates,",
            "            attempt_state.theta, candidates,",
        ),
        "지점: 적격 게이트 × 정보량",
    ),
    Mutation(
        "S08-scores-at-estimate",
        SUNEUNG,
        _SUN_SCORE,
        _swap(_SUN_SCORE, "item_information(theta,", "item_information(attempt_state.theta,"),
        "지점: 후보 점수",
    ),
    # ── 축 8: 처치 기록 키 ─────────────────────────────────────────────────────────
    Mutation(
        "E01-key-written-even-when-equal",
        EVIDENCE,
        _EVD_GATE,
        "    if selection_theta is not None:\n",
        "다를 때만 남긴다",
    ),
    Mutation(
        "E02-key-truthiness",
        EVIDENCE,
        _EVD_GATE,
        "    if selection_theta and selection_theta != theta:\n",
        "0.0 기록",
    ),
    Mutation(
        "E03-key-never-written",
        EVIDENCE,
        _EVD_GATE,
        "    if False:\n",
        "키 기록",
    ),
    Mutation(
        "E04-key-name-changed",
        EVIDENCE,
        'META_KEY_SELECTION_THETA: str = "selection_theta"\n',
        'META_KEY_SELECTION_THETA: str = "sel_theta"\n',
        "소비처가 읽는 키 이름",
    ),
    Mutation(
        "E05-boundary-key-never-written",
        EVIDENCE,
        _EVD_BOUNDARY,
        _swap(_EVD_BOUNDARY, "if theta_boundary is not None:", "if False:"),
        "경계 키 기록",
    ),
    Mutation(
        "E06-boundary-written-when-none",
        EVIDENCE,
        _EVD_BOUNDARY,
        "    meta[META_KEY_THETA_BOUNDARY] = theta_boundary\n",
        "경계 아니면 키 없음(null 기록 금지)",
    ),
    Mutation(
        "E07-boundary-key-name-changed",
        EVIDENCE,
        'META_KEY_THETA_BOUNDARY: str = "theta_boundary"\n',
        'META_KEY_THETA_BOUNDARY: str = "boundary"\n',
        "소비처가 읽는 경계 키 이름",
    ),
    # ── 축 8-b: 정책 버전 식별자 4종(REC-11) — 같은 종류이므로 전건 RED여야 한다 ─────────────
    Mutation(
        "V01-cat-version-old",
        EVIDENCE,
        _EVD_VER_CAT,
        'POLICY_VERSION_CAT: str = "cat_v2"\n',
        "버전: 기본 CAT(옛 값)",
    ),
    Mutation(
        "V02-suneung-version-old",
        EVIDENCE,
        _EVD_VER_SUNEUNG,
        'POLICY_VERSION_SUNEUNG: str = "suneung_v1"\n',
        "버전: 수능(옛 값)",
    ),
    Mutation(
        "V03-remediation-variant-changed",
        EVIDENCE,
        _EVD_VER_REMEDIATION,
        'POLICY_VERSION_CAT_STATE_REMEDIATION: str = "cat_v2_state_remediation"\n',
        "버전: R3 집행 변형(바뀌면 안 된다)",
    ),
    Mutation(
        "V04-undiagnosed-variant-changed",
        EVIDENCE,
        _EVD_VER_UNDIAGNOSED,
        'POLICY_VERSION_CAT_STATE_UNDIAGNOSED: str = "cat_v4_state_undiagnosed"\n',
        "버전: R6 집행 변형(바뀌면 안 된다)",
    ),
    # ── 축 9: 응답 매핑·기록 전달(서빙 경로) — 단위가 못 보는 지점 ─────────────────────
    Mutation(
        "M01-response-selection-is-estimate",
        ME,
        _ME_SEL,
        "        selection_theta=outcome.theta,\n",
        "응답 selection_theta",
        True,
    ),
    Mutation(
        "M02-response-boundary-dropped",
        ME,
        _ME_BOUNDARY,
        "        theta_boundary=None,\n",
        "응답 theta_boundary",
        True,
    ),
    Mutation(
        "M03-ledger-selection-not-passed",
        ME,
        _ME_LEDGER,
        "            theta_boundary=outcome.theta_boundary,\n"
        "            pool_size=outcome.candidate_pool_size,\n",
        "처치 기록 전달(선택 θ)",
        True,
    ),
    Mutation(
        "M04-ledger-boundary-not-passed",
        ME,
        _ME_LEDGER,
        "            selection_theta=outcome.selection_theta,\n"
        "            pool_size=outcome.candidate_pool_size,\n",
        "처치 기록 전달(경계 사실)",
        True,
    ),
    # 서빙 경로 표면에서 다시 보는 핵심 두 건 — "학생 응답이 실제로 바뀌는가"
    Mutation(
        "P01i-policy-uses-estimate-serving",
        POLICY,
        _POL_THETA,
        "        theta = attempt_state.theta\n",
        "서빙: 첫 정답 뒤 도약",
        True,
    ),
    Mutation(
        "X01i-estimator-upper-moved-serving",
        IRT,
        _EST_UPPER,
        _swap(_EST_UPPER, "return upper\n", "return upper - 1.0\n"),
        "서빙: 능력 API·캡처 불변",
        True,
    ),
]

_TOUCHED = (IRT, NPS, POLICY, SUNEUNG, EVIDENCE, ME)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다."""
    for target in _TOUCHED:
        for cached in (target.parent / "__pycache__").glob(f"{target.stem}.*.pyc"):
            cached.unlink()


def run_pytest(*, integration: bool) -> tuple[int, str]:
    """대상 표면을 돌리고 `(종료 코드, 첫 실패 줄)`을 돌려준다.

    판정은 종료 코드로만 한다. 첫 실패 줄은 **보고용**이다 — RED가 "가드가 그 상태를 잡아서"인지
    "주입이 임포트·구문을 깨서"인지 사람이 눈으로 구별하게 한다(후자는 위장 검출이다).
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
    return proc.returncode, failure


def apply_mutation(m: Mutation) -> None:
    """치환 + **적용 실재 단언** — 앵커 1건·결과가 원본과 다름을 쓰기 전에 확인한다."""
    src = m.path.read_text(encoding="utf-8")
    count = src.count(m.old)
    if count != 1:
        raise AssertionError(f"{m.name}: 앵커 {count}건(1건이어야 한다) — 하네스가 대상을 놓쳤다")
    mutated = src.replace(m.old, m.new)
    if mutated == src:
        raise AssertionError(f"{m.name}: 치환 후에도 원본과 동일 — 주입이 들어가지 않았다")
    m.path.write_text(mutated, encoding="utf-8")
    if m.path.read_text(encoding="utf-8") != mutated:
        raise AssertionError(f"{m.name}: 쓴 내용이 다시 읽히지 않는다")


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
        m
        for m in MUTATIONS
        if (args.with_integration or not m.integration) and (not args.only or args.only in m.name)
    ]
    if not selected:
        print("✗ 선택된 뮤테이션이 0건이다 — 이름 조각을 확인하라(빈 실행은 통과가 아니다)")
        return 1
    surfaces = sorted({m.integration for m in selected})
    before = {path: sha256(path) for path in _TOUCHED}

    # ── 성공 방향 대조군 — 무주입이 GREEN이어야 이후 RED가 의미를 가진다 ──
    for integration in surfaces:
        baseline, _ = run_pytest(integration=integration)
        label = "서빙 경로" if integration else "단위"
        print(f"[대조군:{label}] 무주입 exit={baseline} ({'GREEN' if baseline == 0 else 'RED'})")
        if baseline != 0:
            print("✗ 대조군이 이미 RED다 — 이 상태에서는 어떤 뮤테이션도 '검출'로 계상할 수 없다")
            return 1

    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        backups: dict[Path, Path] = {}
        for path in {m.path for m in selected}:
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

        for m in selected:
            try:
                apply_mutation(m)
                code, failure = run_pytest(integration=m.integration)
                detected = code != 0
                mark = "RED(검출)" if detected else "GREEN(생존)"
                surface = "서빙" if m.integration else "단위"
                print(f"  {m.name:<42} [{surface}] axis={m.axis:<28} exit={code} {mark}")
                if failure:
                    print(f"      ↳ {failure[:150]}")
                if not detected:
                    survivors.append(m.name)
            finally:
                shutil.copy2(backups[m.path], m.path)
                if m.path.read_bytes() != backups[m.path].read_bytes():
                    raise AssertionError(f"{m.name}: 원복이 바이트 동일하지 않다 — 중단")

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
