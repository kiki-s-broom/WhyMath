#!/usr/bin/env python3
"""EOS-39 도움 접기 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 "코치가 도움(힌트 단계 2 이상)을 공급해 완료한 문항을 추천 표적용 응답에서 **문항 단위
실패 1건**으로 접는다"는 결정이 만든 여섯 곳이다(판정문
`docs/reviews/eos39_app_help_completion_selection_judgment_2026-10-06.md`):

- `l2/irt.py` — 접기 규칙 · 하한 사다리
- `l2/next_problem_selection.py` — 로더 결선 · 킬 스위치
- `l2/recommendation_evidence.py` — 처치 기록의 계측 키 · 정책 버전 4종
- `l2/recommendation_policy.py` · `api/_next_problem_policy.py` — 관측 필드가 두 정책의 결과로
  흐르는 지점
- `api/me.py` — 처치 기록 전달

추정기 자신을 흔들면(추정기 불변 — 힌트 라벨이 추정 θ·SE를 바꾸면) 동결 테스트가 RED가 되는지도
잰다.

규율은 선례 `scripts/analysis/mutate_eos147_selection_theta_guards.py`와 같다 — 주입 실재 단언
(앵커 1건 · 치환 후 원본과 다름 · 쓴 내용 재확인) · 순수 Python 치환(셸 heredoc 주입 0) · 백업
**복사** 원복(git 원복 금지)과 바이트 동일성 단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 ·
판정은 pytest 종료 코드 · 실행마다 대상 모듈의 바이트코드 캐시 삭제와
`PYTHONDONTWRITEBYTECODE=1` · 실행 전후 sha256 대조.

**각 뮤테이션은 서로 다른 절을 깬다** — "이 절이 없으면 어떤 입력이 통과하는가"에 답하는 반례가
테스트 픽스처에 있어야 그 뮤테이션이 RED가 된다(MISC-07·MISC-23 교훈). 같은 종류가 일부만 RED면
하네스를 의심한다: 정책 버전(`V01`~`V04`)·계측 키 조건(`E01`~`E04`)은 각각 같은 종류이므로
전건 RED여야 한다.

표면이 둘이다:

- **단위**(기본): `tests/backend/l2/test_eos39_help_fold_selection.py` ·
  `tests/backend/l2/test_eos147_selection_theta.py` ·
  `tests/backend/api/test_eos147_selection_theta_suneung.py`
  — DB 없이 규칙·로더·킬 스위치·정책 관측 필드·처치 기록 키·정책 버전.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP 통합 테스트
  `tests/backend/api/test_eos39_help_fold_integration.py`. 환경변수 `WHYMATH_DATABASE_URL`
  (asyncpg URL · **이 브랜치의 head까지 마이그레이션된 DB**)이 필요하다. 코치 대화 → `used_hint`
  귀속 → 다음 추천의 표적까지 실제 스택을 지나는 지점(`api/me.py` 처치 기록 전달 · 로더의
  `used_hint` 조회)은 이 표면에서만 잡힌다.

사용:
    python3 scripts/analysis/mutate_eos39_help_fold_guards.py [--with-integration] [--only 이름조각]

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
    "../../tests/backend/l2/test_eos39_help_fold_selection.py",
    "../../tests/backend/l2/test_eos147_selection_theta.py",
    "../../tests/backend/api/test_eos147_selection_theta_suneung.py",
]
INTEGRATION_TESTS = ["../../tests/backend/api/test_eos39_help_fold_integration.py"]


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
_FOLD_COND = "        if any(row.is_correct and row.used_hint is True for row in rows):\n"
_FOLD_BODY = (
    "            responses.append((rows[0].item, False))\n"
    "            help_failures += 1\n"
    "            continue\n"
)
_FOLD_COUNT = "            help_failures += 1\n"
_UNKNOWN_COND = "            if row.is_correct and row.used_hint is None:\n"
_UNKNOWN_COUNT = "                hint_unknown += 1\n"
_GROUP_KEY = "        if attempt.problem_key not in by_problem:\n"
_RESULT = "    return SelectionEvidence(responses, help_failures, hint_unknown)\n"
_LADDER_GATE = '    if ability_boundary(folded) == "lower":\n'
_LADDER_REACH = "        reach = min(item.difficulty for item, _ in folded) - step\n"
_LADDER_RET = "        return max(lower, min(cold_start, reach))\n"
_LADDER_MLE = "    return estimate_ability(folded)\n"

_LOAD_ATTEMPT = (
    "            selection_attempts.append("
    "SelectionAttempt(pid, item, bool(is_correct), used_hint))\n"
)
_LOAD_HINT_COLUMN = "            ProblemAttempt.used_hint,\n"
_LOAD_BRANCH = "    if evidence.help_failure_count == 0:\n"
_LOAD_FOLDED = "        selection_theta = ability_for_help_folded_selection(evidence.responses)\n"
_LOAD_THETA = "    theta = estimate_ability(responses)\n"
_LOAD_SE = "    se = ability_standard_error(theta, administered_items)\n"
_LOAD_HELP = "        selection_help_count=evidence.help_failure_count,\n"
_LOAD_UNKNOWN = "        selection_hint_unknown_count=evidence.hint_unknown_count,\n"
_KILL = "    if not get_settings().l2_selection_help_fold_enabled:\n"
_KILL_BODY = "        return SelectionEvidence([(a.item, a.is_correct) for a in attempts], 0, 0)\n"
_SEL_RESPONSES = "    selection_theta = ability_for_selection(responses, theta)\n"

_EVD_HELP = (
    "    if selection_help_count > 0:\n"
    "        meta[META_KEY_SELECTION_HELP_COUNT] = selection_help_count\n"
)
_EVD_UNKNOWN = (
    "    if selection_hint_unknown_count > 0:\n"
    "        meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] = selection_hint_unknown_count\n"
)
_EVD_NEG = (
    "    if selection_help_count < 0 or selection_hint_unknown_count < 0:\n"
    "        raise ValueError("
    '"selection_help_count·selection_hint_unknown_count는 음수일 수 없다")\n'
)
_EVD_VER_CAT = 'POLICY_VERSION_CAT: str = "cat_v5"\n'
_EVD_VER_SUNEUNG = 'POLICY_VERSION_SUNEUNG: str = "suneung_v4"\n'
_EVD_VER_REMEDIATION = 'POLICY_VERSION_CAT_STATE_REMEDIATION: str = "cat_v2_state_remediation"\n'
_EVD_VER_UNDIAGNOSED = 'POLICY_VERSION_CAT_STATE_UNDIAGNOSED: str = "cat_v3_state_undiagnosed"\n'

_POL_HELP = '            "selection_help_count": attempt_state.selection_help_count,\n'
_POL_UNKNOWN = (
    '            "selection_hint_unknown_count": attempt_state.selection_hint_unknown_count,\n'
)
_SUN_HELP = '            "selection_help_count": attempt_state.selection_help_count,\n'
_SUN_UNKNOWN = (
    '            "selection_hint_unknown_count": attempt_state.selection_hint_unknown_count,\n'
)
_ME_HELP = "            selection_help_count=outcome.selection_help_count,\n"
_ME_UNKNOWN = "            selection_hint_unknown_count=outcome.selection_hint_unknown_count,\n"


def _swap(old: str, a: str, b: str) -> str:
    """`old` 안의 부분 문자열 `a`를 `b`로 — 앵커와 치환본이 한 곳에서만 갈라지게 한다."""
    assert a in old, (a, old)
    return old.replace(a, b, 1)


MUTATIONS: list[Mutation] = [
    # ── 축 1: 접기 규칙의 절 — 각 절의 반례가 픽스처에 있어야 RED ────────────────────
    Mutation(
        "F01-never-fold",
        IRT,
        _FOLD_COND,
        "        if False:\n",
        "접기 발동(규칙 끄기)",
    ),
    Mutation(
        "F02-fold-without-hint-flag",
        IRT,
        _FOLD_COND,
        "        if any(row.is_correct for row in rows):\n",
        "`used_hint is True` 절(반례: False·None)",
    ),
    Mutation(
        "F03-fold-wrong-rows-too",
        IRT,
        _FOLD_COND,
        "        if any(row.used_hint is True for row in rows):\n",
        "`is_correct` 절(반례: 오답 행의 힌트 표지)",
    ),
    Mutation(
        "F04-hint-none-folds-as-help",
        IRT,
        _FOLD_COND,
        "        if any(row.is_correct and row.used_hint is not False for row in rows):\n",
        "미상(NULL)을 도움으로(모른다 ≠ 아니다)",
    ),
    Mutation(
        "F05-fold-only-when-no-wrong-row",
        IRT,
        _FOLD_COND,
        "        if all(row.is_correct and row.used_hint is True for row in rows):\n",
        "문항 단위 접기(오답 행 + 도움 완료 = 1건)",
    ),
    Mutation(
        "F06-fold-keeps-the-correct-row",
        IRT,
        _FOLD_BODY,
        "            responses.append((rows[0].item, False))\n"
        "            responses.extend((row.item, row.is_correct) for row in rows)\n"
        "            help_failures += 1\n"
        "            continue\n",
        "접힌 문항은 응답 1건(행 단위 후퇴)",
    ),
    Mutation(
        "F07-fold-emits-a-correct-response",
        IRT,
        _FOLD_BODY,
        _swap(_FOLD_BODY, "(rows[0].item, False)", "(rows[0].item, True)"),
        "접힌 응답의 정오",
    ),
    Mutation(
        "F08-fold-count-not-incremented",
        IRT,
        _FOLD_COUNT,
        "            help_failures += 0\n",
        "접힘 수(발동률의 분자)",
    ),
    Mutation(
        "F09-unknown-not-counted",
        IRT,
        _UNKNOWN_COUNT,
        "                hint_unknown += 0\n",
        "미상 수",
    ),
    Mutation(
        "F10-unknown-counts-wrong-rows",
        IRT,
        _UNKNOWN_COND,
        "            if row.used_hint is None:\n",
        "미상 수는 정답 행만(반례: 오답 행의 NULL)",
    ),
    Mutation(
        "F11-group-by-row-not-problem",
        IRT,
        _GROUP_KEY,
        "        if True:\n",
        "문항 단위 묶음",
    ),
    Mutation(
        "F12-result-counts-swapped",
        IRT,
        _RESULT,
        "    return SelectionEvidence(responses, hint_unknown, help_failures)\n",
        "결과 필드 순서",
    ),
    # ── 축 2: 하한 사다리 — 도움 접기가 만든 전부 실패에만 ─────────────────────────────
    Mutation(
        "L01-ladder-pins-the-lower-bound",
        IRT,
        _LADDER_RET,
        "        return lower\n",
        "사다리가 아니라 하한 고정(−4.0)",
    ),
    Mutation(
        "L02-no-cold-start-cap",
        IRT,
        _LADDER_RET,
        "        return max(lower, reach)\n",
        "콜드스타트 상한(시작점 위로 안 올림)",
    ),
    Mutation(
        "L03-no-lower-floor",
        IRT,
        _LADDER_RET,
        "        return min(cold_start, reach)\n",
        "하한 바닥(−4.0)",
    ),
    Mutation(
        "L04-highest-failed-difficulty",
        IRT,
        _LADDER_REACH,
        _swap(_LADDER_REACH, "min(", "max("),
        "실패한 최저 난이도 앵커",
    ),
    Mutation(
        "L05-step-added-not-subtracted",
        IRT,
        _LADDER_REACH,
        _swap(_LADDER_REACH, ") - step", ") + step"),
        "사다리 방향(아래로)",
    ),
    Mutation(
        "L06-ladder-never-applies",
        IRT,
        _LADDER_GATE,
        "    if False:\n",
        "사다리 발동(전부 실패일 때)",
    ),
    Mutation(
        "L07-ladder-applies-to-mixed",
        IRT,
        _LADDER_GATE,
        '    if ability_boundary(folded) != "upper":\n',
        "혼합 이력은 MLE(사다리 오발동)",
    ),
    Mutation(
        "L08-folded-mixed-returns-cold-start",
        IRT,
        _LADDER_MLE,
        "    return estimate_ability([])\n",
        "접힌 혼합 이력은 MLE",
    ),
    # ── 축 3: 로더 결선 — 규칙이 서빙 경로에서 실제로 도달하는가 ────────────────────────
    Mutation(
        "W01-loader-never-uses-the-folded-theta",
        NPS,
        _LOAD_BRANCH,
        "    if True:\n",
        "로더 결선(접기 결과를 선택 θ로)",
    ),
    Mutation(
        "W02-loader-always-uses-the-folded-theta",
        NPS,
        _LOAD_BRANCH,
        "    if False:\n",
        "접기 없는 이력은 EOS-147 규칙",
    ),
    Mutation(
        "W03-loader-uses-the-estimate-for-the-folded-case",
        NPS,
        _LOAD_FOLDED,
        "        selection_theta = theta\n",
        "접힌 이력의 선택 θ가 추정 θ",
    ),
    Mutation(
        "W04-hint-label-dropped-from-the-attempt",
        NPS,
        _LOAD_ATTEMPT,
        "            selection_attempts.append("
        "SelectionAttempt(pid, item, bool(is_correct), None))\n",
        "힌트 라벨 전달(항상 미상)",
    ),
    Mutation(
        "W05-hint-column-not-selected",
        NPS,
        _LOAD_HINT_COLUMN,
        "",
        "`used_hint` 조회 컬럼",
    ),
    Mutation(
        "W06-estimate-reads-the-folded-responses",
        NPS,
        _LOAD_THETA,
        "    theta = estimate_ability(selection_evidence(selection_attempts).responses)\n",
        "추정기 불변(힌트 라벨이 추정 θ에 들어가면 안 된다)",
    ),
    Mutation(
        "W07-help-count-not-passed",
        NPS,
        _LOAD_HELP,
        "        selection_help_count=0,\n",
        "상태 객체의 접힘 수",
    ),
    Mutation(
        "W08-unknown-count-not-passed",
        NPS,
        _LOAD_UNKNOWN,
        "        selection_hint_unknown_count=0,\n",
        "상태 객체의 미상 수",
    ),
    # ── 축 4: 킬 스위치 ───────────────────────────────────────────────────────────
    Mutation(
        "K01-kill-switch-ignored",
        NPS,
        _KILL,
        "    if False:\n",
        "킬 스위치(끄면 종전 동작)",
    ),
    Mutation(
        "K02-kill-switch-inverted",
        NPS,
        _KILL,
        "    if get_settings().l2_selection_help_fold_enabled:\n",
        "킬 스위치 방향",
    ),
    Mutation(
        "K03-off-still-counts-folds",
        NPS,
        _KILL_BODY,
        "        return SelectionEvidence(\n"
        "            [(a.item, a.is_correct) for a in attempts],\n"
        "            selection_evidence(attempts).help_failure_count,\n"
        "            0,\n"
        "        )\n",
        "꺼진 상태의 접힘 수(0이어야 한다)",
    ),
    # ── 축 5: 처치 기록 — 계측 키 ─────────────────────────────────────────────────
    Mutation(
        "E01-help-key-always-written",
        EVIDENCE,
        _EVD_HELP,
        "    if True:\n        meta[META_KEY_SELECTION_HELP_COUNT] = selection_help_count\n",
        "접힘 키는 0이면 없다(발동률의 분모 의미)",
    ),
    Mutation(
        "E02-help-key-never-written",
        EVIDENCE,
        _EVD_HELP,
        "    if False:\n        meta[META_KEY_SELECTION_HELP_COUNT] = selection_help_count\n",
        "접힘 키 기록",
    ),
    Mutation(
        "E03-unknown-key-always-written",
        EVIDENCE,
        _EVD_UNKNOWN,
        "    if True:\n"
        "        meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] = selection_hint_unknown_count\n",
        "미상 키는 0이면 없다",
    ),
    Mutation(
        "E04-unknown-key-never-written",
        EVIDENCE,
        _EVD_UNKNOWN,
        "    if False:\n"
        "        meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] = selection_hint_unknown_count\n",
        "미상 키 기록",
    ),
    Mutation(
        "E05-negative-counts-accepted",
        EVIDENCE,
        _EVD_NEG,
        "",
        "음수 계수는 호출 오류",
    ),
    # ── 축 6: 정책 버전 4종 — 같은 종류라 전건 RED ──────────────────────────────────
    Mutation(
        "V01-cat-version-not-bumped",
        EVIDENCE,
        _EVD_VER_CAT,
        'POLICY_VERSION_CAT: str = "cat_v4"\n',
        "기본 CAT 판",
    ),
    Mutation(
        "V02-suneung-version-not-bumped",
        EVIDENCE,
        _EVD_VER_SUNEUNG,
        'POLICY_VERSION_SUNEUNG: str = "suneung_v3"\n',
        "수능 판",
    ),
    Mutation(
        "V03-r3-version-not-bumped",
        EVIDENCE,
        _EVD_VER_REMEDIATION,
        'POLICY_VERSION_CAT_STATE_REMEDIATION: str = "cat_v1_state_remediation"\n',
        "R3 변형 판(도움 접기가 R3의 선택 θ를 바꾼다)",
    ),
    Mutation(
        "V04-r6-version-not-bumped",
        EVIDENCE,
        _EVD_VER_UNDIAGNOSED,
        'POLICY_VERSION_CAT_STATE_UNDIAGNOSED: str = "cat_v2_state_undiagnosed"\n',
        "R6 변형 판",
    ),
    # ── 축 7: 관측 필드가 두 정책 결과로 흐르는 지점 ─────────────────────────────────
    Mutation(
        "P01-cat-help-count-dropped",
        POLICY,
        _POL_HELP,
        '            "selection_help_count": 0,\n',
        "기본 CAT 결과의 접힘 수",
    ),
    Mutation(
        "P02-cat-unknown-count-dropped",
        POLICY,
        _POL_UNKNOWN,
        '            "selection_hint_unknown_count": 0,\n',
        "기본 CAT 결과의 미상 수",
    ),
    Mutation(
        "P03-suneung-help-count-dropped",
        SUNEUNG,
        _SUN_HELP,
        '            "selection_help_count": 0,\n',
        "수능 결과의 접힘 수",
    ),
    Mutation(
        "P04-suneung-unknown-count-dropped",
        SUNEUNG,
        _SUN_UNKNOWN,
        '            "selection_hint_unknown_count": 0,\n',
        "수능 결과의 미상 수",
    ),
    # ── 축 8: 서빙 경로 — 처치 기록 전달(HTTP 통합에서만 잡힌다) ─────────────────────
    Mutation(
        "M01-ledger-help-count-not-passed", ME, _ME_HELP, "", "처치 기록의 접힘 수 전달", True
    ),
    Mutation(
        "M02-ledger-unknown-count-not-passed",
        ME,
        _ME_UNKNOWN,
        "",
        "처치 기록의 미상 수 전달(단위가 못 본다)",
        True,
    ),
    # ── 축 9: 서빙 경로 — 로더의 `used_hint` 조회(통합) ──────────────────────────────
    Mutation(
        "S01-hint-column-not-selected-serving",
        NPS,
        _LOAD_HINT_COLUMN,
        "",
        "서빙: `used_hint` 조회(코치 완료 → 다음 추천)",
        True,
    ),
    Mutation(
        "S02-fold-off-in-serving",
        NPS,
        _KILL,
        "    if True:\n",
        "서빙: 접기가 꺼진 채 배포(도움 완료 = 독립 성공)",
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
    compile(mutated, str(m.path), "exec")  # 주입이 구문을 깨면 '검출'이 아니라 하네스 결함이다


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
                code, failure, summary = run_pytest(integration=m.integration)
                if code == 0 and "skipped" in summary:
                    failure = f"무효: 뮤테이션 실행이 건너뜀 — {summary}"
                detected = code != 0
                mark = "RED(검출)" if detected else "GREEN(생존)"
                surface = "서빙" if m.integration else "단위"
                print(f"  {m.name:<46} [{surface}] axis={m.axis:<34} exit={code} {mark}")
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
