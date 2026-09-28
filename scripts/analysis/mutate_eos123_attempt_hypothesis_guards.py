#!/usr/bin/env python3
"""EOS-123 정답 회차 가설 정책 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 채점 1회차가 오개념 가설에 하는 일이다: `l4/misconception/attempt_hypothesis_policy.py`의
6칸 표(정오답 × 훑기 3상태)와 `api/me.py`의 배선(훑기 호출 · 행동별 분기 · 충돌 로그). 설계
정본은 `docs/reviews/eos123_correct_attempt_refutation_judgment_2026-09-28.md`(§9가 이 하네스의
실행 결과를 인용한다).

규율은 선례 `scripts/analysis/mutate_eos26_r6_guards.py`와 같다 — 주입 실재 단언(앵커 1건 ·
치환 후 원본과 다름) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트 동일성 단언 ·
중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은 pytest 종료 코드 · 실행마다 대상 모듈의
바이트코드 캐시 삭제(`HARN-120` ⑤ — 같은 1초 안에 크기 변화가 같은 두 뮤테이션을 쓰면 앞
뮤테이션의 캐시가 실행된다).

표면이 둘이다:

- **단위**(기본): 정책 단위 테스트 + `tests/backend/api/test_me.py`의 채점 경로 4개 클래스 — DB 없이
  표와 배선을 잰다(`apply_candidates`는 기록 대역).
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP 경로 — EOS-123 실 PG 판정과 페르소나 C.
  환경변수 `WHYMATH_DATABASE_URL`(asyncpg URL · 마이그레이션 적용된 DB)이 필요하다. 이 표면은
  "대역에서 잡힌다"가 아니라 "가설 행이 실제로 그렇게 영속된다"를 확인한다.

**등가 뮤테이션이라 넣지 않은 것**: `DECAY_ONLY` 분기가 빈 튜플 대신 훑기 후보를 넘기는 변형 —
그 분기는 `ran_no_candidate`에서만 나오고 그때 후보는 구성상 0건이라 관측 가능한 차이가 없다.

사용: `python3 scripts/analysis/mutate_eos123_attempt_hypothesis_guards.py [--with-integration]
[--only 이름조각]` · 종료 코드 0 = 전건 검출 · 1 = 생존한 뮤테이션 있음(가드가 위장이다) 또는
대조군 RED.
"""

from __future__ import annotations

import argparse
import atexit
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

POLICY = BACKEND / "whymath_backend" / "l4" / "misconception" / "attempt_hypothesis_policy.py"
ME = BACKEND / "whymath_backend" / "api" / "me.py"

_TEST_ME = "../../tests/backend/api/test_me.py"
UNIT_TESTS = [
    "../../tests/backend/l4/misconception/test_attempt_hypothesis_policy.py",
    f"{_TEST_ME}::TestAttemptCorrectAnswerHypothesis",
    f"{_TEST_ME}::TestAttemptMisconceptionScan",
    f"{_TEST_ME}::TestAttemptMisconceptionReviewCoaching",
    f"{_TEST_ME}::TestAttemptDistractorLink",
]
INTEGRATION_TESTS = [
    "../../tests/backend/api/test_eos123_correct_attempt_decay_pg.py",
    "../../tests/backend/api/test_e2e_persona_journeys.py"
    "::test_persona_c_misconception_confidence_declines_after_targeted_problem",
]


@dataclass(frozen=True)
class Mutation:
    """뮤테이션 1건 — 어느 파일의 어느 절을 무엇으로 바꾸는가 + 어느 표면이 RED여야 하는가."""

    name: str
    path: Path
    old: str
    new: str
    axis: str  # 이 뮤테이션이 검사하는 축(보고용)
    integration: bool = False  # True면 실 PG 서빙 경로 표면에서 판정한다


# ── 정책 표의 칸(리터럴 앵커 — 표를 import하지 않는 단위 테스트가 잡아야 한다) ─────────
_CELL_CORRECT_NO_CAND = (
    "(True, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.DECAY_ONLY,"
)
_CELL_CORRECT_WITH_CAND = (
    "(True, MisconceptionScan.RAN_WITH_CANDIDATES): AttemptHypothesisAction.HOLD_CONFLICT,"
)
_CELL_CORRECT_NOT_RUN = "(True, MisconceptionScan.NOT_RUN): AttemptHypothesisAction.NONE,"
_CELL_WRONG_NO_CAND = "(False, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.APPLY,"
_TYPE_GUARD = (
    "    if not isinstance(is_correct, bool):\n"
    '        raise TypeError(f"is_correct는 bool이어야 한다: {type(is_correct).__name__}")\n'
)

# ── 배선(api/me.py) ───────────────────────────────────────────────────────────
_SCAN_CALL_MATERIAL = (
    "        answer=body.student_answer,\n"
    "        selected_choice_index=body.selected_choice_index,\n"
    "    )\n"
    "    evidence = await collect_assessment_evidence("
)
_DECAY_BRANCH = (
    "        # 반환값을 쓰지 않는다 — 정답 회차는 복습 코칭을 만들지 않는다"
    "(바로 위 APPLY 분기 주석).\n"
    "        await apply_candidates(session, user.user_id, ())\n"
    "        await session.commit()\n"
)
_HOLD_HEAD = "    elif hypothesis_action is AttemptHypothesisAction.HOLD_CONFLICT:\n"
_HOLD_LOG = (
    "        _logger.warning(\n"
    '            "정답 보고와 오개념 관측이 충돌 — 가설을 갱신하지 않는다(EOS-123 보류). "\n'
    '            "problem_id=%s misconception_ids=%s",\n'
    "            body.problem_id,\n"
    '            ",".join(c.misconception_id for c in misconception_scan_result.candidates),\n'
    "        )\n"
)
_HOLD_LOG_ARGS = (
    '            "problem_id=%s misconception_ids=%s",\n'
    "            body.problem_id,\n"
    '            ",".join(c.misconception_id for c in misconception_scan_result.candidates),\n'
    "        )\n"
)

MUTATIONS: list[Mutation] = [
    # ── 정책 표(판정문 §0 6칸) ────────────────────────────────────────────────────
    Mutation(
        "M01-correct-no-candidate-untouched",
        POLICY,
        _CELL_CORRECT_NO_CAND,
        "(True, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.NONE,",
        "정답 감쇠(원래 결함 형태)",
    ),
    Mutation(
        "M02-conflict-decays",
        POLICY,
        _CELL_CORRECT_WITH_CAND,
        "(True, MisconceptionScan.RAN_WITH_CANDIDATES): AttemptHypothesisAction.DECAY_ONLY,",
        "충돌 보류(F2)",
    ),
    Mutation(
        "M03-conflict-reinforces",
        POLICY,
        _CELL_CORRECT_WITH_CAND,
        "(True, MisconceptionScan.RAN_WITH_CANDIDATES): AttemptHypothesisAction.APPLY,",
        "충돌 강화 금지(오탐)",
    ),
    Mutation(
        "M04-correct-not-run-decays",
        POLICY,
        _CELL_CORRECT_NOT_RUN,
        "(True, MisconceptionScan.NOT_RUN): AttemptHypothesisAction.DECAY_ONLY,",
        "not_run 불변식(F1·F7)",
    ),
    Mutation(
        "M05-wrong-no-candidate-untouched",
        POLICY,
        _CELL_WRONG_NO_CAND,
        "(False, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.NONE,",
        "오답 감쇠(현행 보존)",
    ),
    Mutation("M06-type-guard-removed", POLICY, _TYPE_GUARD, "", "모름≠오답"),
    # ── 배선(api/me.py) ────────────────────────────────────────────────────────
    Mutation(
        "M07-decay-branch-coaches",
        ME,
        _DECAY_BRANCH,
        "        decayed = await apply_candidates(session, user.user_id, ())\n"
        "        await session.commit()\n"
        "        misconception_review_coaching = "
        "recommend_misconception_review_coaching(decayed)\n",
        "정답 회차 코칭 금지(F10)",
    ),
    Mutation("M08-decay-branch-dead", ME, _DECAY_BRANCH, "        pass\n", "정답 감쇠 배선"),
    Mutation(
        "M09-decay-two-turns",
        ME,
        _DECAY_BRANCH,
        "        await apply_candidates(session, user.user_id, (), turns_elapsed=2)\n"
        "        await session.commit()\n",
        "강도 상한 1턴",
    ),
    Mutation(
        "M10-hold-decays",
        ME,
        _HOLD_HEAD,
        _HOLD_HEAD + "        await apply_candidates(session, user.user_id, ())\n",
        "충돌 보류 배선(F2)",
    ),
    Mutation("M11-hold-log-removed", ME, _HOLD_LOG, "        pass\n", "충돌 관측성"),
    Mutation(
        "M12-hold-log-leaks-answer",
        ME,
        _HOLD_LOG_ARGS,
        '            "problem_id=%s misconception_ids=%s answer=%s",\n'
        "            body.problem_id,\n"
        '            ",".join(c.misconception_id for c in misconception_scan_result.candidates),\n'
        "            body.student_answer,\n"
        "        )\n",
        "PII(답안 원문)",
    ),
    Mutation(
        "M13-scan-skips-correct",
        ME,
        _SCAN_CALL_MATERIAL,
        "        answer=None if body.is_correct else body.student_answer,\n"
        "        selected_choice_index=None if body.is_correct else body.selected_choice_index,\n"
        "    )\n"
        "    evidence = await collect_assessment_evidence(",
        "정답도 같은 조건으로 훑기(F1)",
    ),
    # ── 서빙 경로(실 PG) — 가설 행이 실제로 그렇게 영속되는가 ─────────────────────
    Mutation(
        "I01-correct-no-candidate-untouched",
        POLICY,
        _CELL_CORRECT_NO_CAND,
        "(True, MisconceptionScan.RAN_NO_CANDIDATE): AttemptHypothesisAction.NONE,",
        "정답 감쇠 영속",
        True,
    ),
    Mutation(
        "I02-hold-decays",
        ME,
        _HOLD_HEAD,
        _HOLD_HEAD + "        await apply_candidates(session, user.user_id, ())\n",
        "충돌 행 불변",
        True,
    ),
    Mutation(
        "I03-correct-not-run-decays",
        POLICY,
        _CELL_CORRECT_NOT_RUN,
        "(True, MisconceptionScan.NOT_RUN): AttemptHypothesisAction.DECAY_ONLY,",
        "미관측 행 불변",
        True,
    ),
    Mutation(
        "I04-decay-two-turns",
        ME,
        _DECAY_BRANCH,
        "        await apply_candidates(session, user.user_id, (), turns_elapsed=2)\n"
        "        await session.commit()\n",
        "강도 상한 영속",
        True,
    ),
    Mutation(
        "I05-scan-skips-correct",
        ME,
        _SCAN_CALL_MATERIAL,
        "        answer=None if body.is_correct else body.student_answer,\n"
        "        selected_choice_index=None if body.is_correct else body.selected_choice_index,\n"
        "    )\n"
        "    evidence = await collect_assessment_evidence(",
        "정답 훑기 영속",
        True,
    ),
]


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다."""
    for target in (POLICY, ME):
        for cached in (target.parent / "__pycache__").glob(f"{target.stem}.*.pyc"):
            cached.unlink()


#: 서빙 경로 표면이 skip으로 끝났다는 표식(pytest 종료 코드와 겹치지 않는 값).
SKIPPED = 97


def run_pytest(*, integration: bool) -> int:
    """대상 표면을 돌리고 **종료 코드**를 돌려준다(화면 문자열로 판정하지 않는다).

    예외 하나: 서빙 경로가 skip으로 끝나면 `SKIPPED`를 돌려준다. 통합 테스트는
    `WHYMATH_RUN_INTEGRATION` 누락·PG 미도달에서 **skip으로 exit 0**을 내므로, 이 검사가 없으면
    대조군과 뮤테이션이 둘 다 "GREEN"이 되어 하네스 전체가 공허해진다(2026-09-28 이 세션 실측 —
    플래그 없이 돌린 첫 실행이 `2 skipped`·exit 0이었다).
    """
    drop_bytecode()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
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
        "-x",
    ]
    targets = UNIT_TESTS
    if integration:
        env.update(WHYMATH_RUN_INTEGRATION="1", WHYMATH_DB_DISABLE_POOL="1")
        args += ["-m", "integration"]
        targets = INTEGRATION_TESTS
    # HARN-19: 서브프로세스 출력 디코딩은 인코딩을 명시한다. 매달리는 뮤테이션은 원복을 건너뛰게
    # 하므로 시간 상한을 건다.
    proc = subprocess.run(
        [*args, *targets],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1500,
    )
    lines = proc.stdout.strip().splitlines()
    summary = lines[-1] if lines else ""
    if integration and "skipped" in summary:
        return SKIPPED
    return proc.returncode


def classify(code: int) -> str:
    """종료 코드 → 판정. **1만 검출**이다 — 수집 오류(2)·사용 오류(4)·테스트 0건(5)·skip은
    "가드가 막았다"가 아니라 "판정하지 못했다"이므로 검출로 세지 않는다."""
    if code == 1:
        return "RED(검출)"
    if code == 0:
        return "GREEN(생존)"
    return f"판정 불가(exit={code})"


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
    surfaces = sorted({m.integration for m in selected})

    # ── 성공 방향 대조군 — 무주입이 GREEN이어야 이후 RED가 의미를 가진다 ──
    for integration in surfaces:
        baseline = run_pytest(integration=integration)
        label = "서빙 경로" if integration else "단위"
        # 대조군에는 변이용 문구("생존")를 쓰지 않는다 — 0이면 그냥 GREEN이다.
        state = "GREEN" if baseline == 0 else classify(baseline)
        print(f"[대조군:{label}] 무주입 exit={baseline} ({state})")
        if baseline != 0:
            print("✗ 대조군이 GREEN이 아니다 — 어떤 뮤테이션도 '검출'로 계상할 수 없다")
            return 1

    with tempfile.TemporaryDirectory() as tmp:
        backups: dict[Path, Path] = {}
        for path in {m.path for m in selected}:
            backup = Path(tmp) / path.name
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

        survivors: list[str] = []
        for m in selected:
            try:
                apply_mutation(m)
                code = run_pytest(integration=m.integration)
                verdict = classify(code)
                detected = code == 1
                surface = "서빙" if m.integration else "단위"
                print(f"  {m.name:<38} [{surface}] axis={m.axis:<22} {verdict}")
                if not detected:
                    survivors.append(m.name)
            finally:
                shutil.copy2(backups[m.path], m.path)
                if m.path.read_bytes() != backups[m.path].read_bytes():
                    raise AssertionError(f"{m.name}: 원복이 바이트 동일하지 않다 — 중단")

    print()
    if survivors:
        print(f"✗ 생존 {len(survivors)}/{len(selected)}: {', '.join(survivors)}")
        print("  생존한 뮤테이션은 '가드가 그 상태를 막지 못한다'는 뜻이다 — 보호로 계상 불가.")
        return 1
    print(f"✓ 전건 검출 {len(selected)}/{len(selected)} — 각 가드가 실제로 그 상태를 막는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
