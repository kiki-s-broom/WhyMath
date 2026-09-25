#!/usr/bin/env python3
"""SCENARIO-001~010 회귀 스위트의 **변별력** 검증 — 시나리오마다 회귀 1건을 주입해 RED를 확인한다.

`tests/backend/scenarios/test_phase2_scenario_regression_suite.py`가 초록인 것은 보호의 증거가
아니다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"). 이 스크립트는 **서빙
코드**(`src/backend/whymath_backend`)에 "그 시나리오가 없으면 통과해 버리는 회귀"를 시나리오마다
하나씩 주입하고, 스위트 전체를 돌려 ①지목한 시나리오가 RED인지 ②그 밖에 어느 시나리오가 함께
RED인지(교차 검출 행렬)를 기록한다.

**주입 자체의 실재도 단언한다**(2026-09-06 규칙): 치환 대상이 정확히 1건인지, 치환 후 파일이
원본과 다른지, 원복이 바이트 동일한지(sha256)를 각각 확인한다. 주입이 조용히 실패하면 정상
파일에 대해 테스트가 돌고 "passed"가 *검출 실패*가 아니라 *검출*처럼 보인다.

원복은 `git checkout`이 아니라 **바이트 백업 복원**이다(CLAUDE.md 2026-08-10 규칙) — 트리에
미커밋 작업분이 있으면 git 계열 원복이 그것까지 되돌린다.

판정은 **exit code가 아니라 junitxml의 테스트별 결과**로 낸다 — 어느 시나리오가 RED인지가
판정 대상이라 스위트 전체의 exit 1만으로는 "지목한 시나리오가 잡았다"를 말할 수 없다.
단 pytest의 exit code도 함께 검사한다: junitxml이 비었거나 수집 오류(exit 2·3·4)면 그 회차는
**측정 실패**로 분류한다(0건 통과로 위장하지 않는다).

판정: 전 뮤테이션의 지목 시나리오가 RED면 exit 0, 하나라도 살아남거나 측정 실패면 exit 1.

실행(src/backend의 실 PG가 필요 — CI `backend-migrations` 잡과 같은 환경):

    WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath \\
        python scripts/ops/verify_scenario_suite_discrimination.py [--only M005]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "src" / "backend"
PKG = BACKEND / "whymath_backend"
SUITE = "../../tests/backend/scenarios/test_phase2_scenario_regression_suite.py"


@dataclass(frozen=True)
class Mutation:
    """회귀 1건 — 대상 파일의 원본 절(정확히 1건)을 치환 절로 바꾼다."""

    mid: str
    scenario: str  # 지목 시나리오(예: "001") — 이것이 RED여야 통과
    target: pathlib.Path
    old: str
    new: str
    why: str  # 이 회귀가 무엇을 끊는가


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M001-no-learning-entry",
        "001",
        PKG / "l2" / "learning_state_machine.py",
        "    trigger = _LEARNING_ENTRY_TRIGGERS.get(current)",
        "    trigger = None  # MUTANT — 신규 학생의 학습 진입 전이를 적재하지 않는다",
        "신규 학생(NEW)의 학습 진입 전이 누락 → 첫 평가 전이가 거부된다",
    ),
    Mutation(
        "M002-capture-drops-weak-points",
        "002",
        PKG / "api" / "me.py",
        '    weak_point_items = [w.model_dump(mode="json") for w in weak]',
        "    weak_point_items: list[dict[str, object]] = []  # MUTANT — 약점 조립 누락",
        "진단 확정이 약점을 싣지 않는다 → 낮은 진단점수가 상태로 서지 않는다",
    ),
    Mutation(
        "M003-weak-only-filter-off",
        "003",
        PKG / "l2" / "prerequisite_recommendation.py",
        "        if weak_only and (weakness is None or weakness >= mastery_threshold):",
        "        if False:  # MUTANT — 결손 필터 무력화(미측정 선수까지 결손으로 보고)",
        "측정 없는 선수를 결손으로 분류한다 → 결손 판정이 근거 없이 선다",
    ),
    Mutation(
        "M004-repeated-failure-off-by-one",
        "004",
        PKG / "l2" / "learning_state_policy.py",
        "            not e.is_correct and e.consecutive_failures >= REPEATED_FAILURE_THRESHOLD",
        "            not e.is_correct and e.consecutive_failures > REPEATED_FAILURE_THRESHOLD",
        "반복 실패 경계 off-by-one → 같은 오개념 3회째에도 교정만 반복한다",
    ),
    Mutation(
        "M005-coach-completion-skips-mastery",
        "005",
        PKG / "api" / "coach.py",
        "    await record_problem_attempt_mastery(session, evidence=completion_evidence)",
        "    pass  # MUTANT — 코치 완료가 숙달을 전파하지 않는다",
        "힌트 후 코치 대화로 정답을 내도 숙달이 측정되지 않는다(attempt만 남는다)",
    ),
    Mutation(
        "M006-hint-ladder-not-recovered",
        "006",
        PKG / "api" / "coach.py",
        (
            "    server_prev_hint = await _prev_hint_level_for(\n"
            "        session, user_id=user.user_id, problem_id=body.problem_id\n"
            "    )"
        ),
        (
            "    server_prev_hint = None  # MUTANT — 새 대화가 원장의 직전 힌트 단계를 잊는다\n"
            "    _unused_prev = await _prev_hint_level_for(\n"
            "        session, user_id=user.user_id, problem_id=body.problem_id\n"
            "    )"
        ),
        "새 대화를 열면 힌트 사다리가 리셋된다 → AI Tutor가 학생의 막힘 이력을 잊는다",
    ),
    Mutation(
        "M007-threshold-drift",
        "007",
        PKG / "l2" / "recommendation_contract.py",
        "    if mastery <= WEAK_CONCEPT_MASTERY_CEILING:",
        "    if mastery <= 0.95:  # MUTANT — 추천 경계가 약점 경계와 어긋난다",
        "추천 근거의 경계(0.7)가 표류 → 숙달을 넘겨도 '현재 개념 연습'에 머문다",
    ),
    Mutation(
        "M008-confidence-never-high",
        "008",
        PKG / "l2" / "learning_state_policy.py",
        (
            "    return evidence.confidence is not None"
            " and evidence.confidence >= HIGH_CONFIDENCE_THRESHOLD"
        ),
        "    return False  # MUTANT — 자기보고 확신도를 읽지 않는다",
        "확신 있는 정답도 진급(ADVANCING)하지 못한다 → 다음 concept 이동의 정책 축이 끊긴다",
    ),
    Mutation(
        "M009-dialogue-resolution-dropped",
        "009",
        PKG / "api" / "me.py",
        "        row.resolution = body.resolution",
        "        pass  # MUTANT — 대화 종결 보고를 영속하지 않는다",
        "세션(대화) 종료 보고가 사라진다 → 재접속 후 종료 상태가 복원되지 않는다",
    ),
    Mutation(
        "M010-state-not-read-from-ledger",
        "010",
        PKG / "l2" / "learning_state_machine.py",
        "    return latest if latest is not None else INITIAL_STATE",
        "    return INITIAL_STATE  # MUTANT — 원장을 읽지 않고 항상 초기 상태",
        "학습 상태를 원장에서 복구하지 않는다 → 재접속 시 NEW로 되돌아간다",
    ),
)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scenario_of(testcase_name: str) -> str | None:
    """`test_scenario_007_...` → "007"."""
    parts = testcase_name.split("_")
    if len(parts) >= 3 and parts[0] == "test" and parts[1] == "scenario":
        return parts[2]
    return None


def _run_suite(junit: pathlib.Path) -> tuple[int, dict[str, str]]:
    """스위트를 돌려 (pytest exit code, 시나리오별 결과 {"001": "passed"|"failed"|...})."""
    env = dict(os.environ)
    env.setdefault("WHYMATH_DATABASE_URL", "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")
    env["WHYMATH_RUN_INTEGRATION"] = "1"
    env["WHYMATH_DB_DISABLE_POOL"] = "1"
    if junit.exists():
        junit.unlink()  # 이전 회차 결과를 이번 것으로 오독하지 않는다
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pyproject.toml",
            SUITE,
            "-m",
            "integration",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",  # 로케일 디코드 금지(HARN-19)
        timeout=900,
    )
    outcomes: dict[str, str] = {}
    if junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            sid = _scenario_of(case.get("name", ""))
            if sid is None:
                continue
            if case.find("failure") is not None or case.find("error") is not None:
                outcomes[sid] = "failed"
            elif case.find("skipped") is not None:
                outcomes[sid] = "skipped"
            else:
                outcomes[sid] = "passed"
    if proc.returncode not in (0, 1) or len(outcomes) != 10:
        # 측정 실패의 원인을 남긴다 — 끝부분만이 아니라 stderr 전량(잘라서 판정 금지).
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    return proc.returncode, outcomes


def _measured(code: int, outcomes: dict[str, str]) -> bool:
    """판정 가능한 회차인가 — 10종 전부 결과가 있고 skip 0건, 수집 오류 아님."""
    return (
        code in (0, 1)
        and len(outcomes) == 10
        and all(v in ("passed", "failed") for v in outcomes.values())
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="이 id로 시작하는 뮤테이션만 실행(예: M005)")
    args = parser.parse_args()
    selected = [m for m in MUTATIONS if args.only is None or m.mid.startswith(args.only)]
    if not selected:
        print(f"✗ --only {args.only}에 해당하는 뮤테이션이 없다.")
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        junit = pathlib.Path(tmp) / "junit.xml"
        # 0) 기준선 — 정상 상태에서 10종 전건 통과해야 뒤의 RED를 해석할 수 있다.
        code, base = _run_suite(junit)
        print(f"BASELINE exit={code} outcomes={dict(sorted(base.items()))}")
        if not _measured(code, base) or any(v != "passed" for v in base.values()):
            print("✗ 기준선이 전건 통과가 아니다(또는 측정 실패) — 뮤테이션 결과를 해석할 수 없다.")
            return 1

        for m in selected:
            backup = pathlib.Path(tmp) / f"{m.mid}.bak"
            shutil.copy2(m.target, backup)
            original_sha = _sha(m.target)
            src = m.target.read_text(encoding="utf-8")
            count = src.count(m.old)
            if count != 1:
                print(f"✗ {m.mid}: 치환 대상이 {count}건이다(기대 1) — 주입 하네스 결함.")
                failures.append(f"{m.mid}(주입 불가)")
                continue
            mutated = src.replace(m.old, m.new, 1)
            assert mutated != src, f"{m.mid}: 치환했는데 내용이 같다"
            m.target.write_text(mutated, encoding="utf-8")
            assert _sha(m.target) != original_sha, f"{m.mid}: 주입 후 해시가 원본과 같다"
            try:
                code, outcomes = _run_suite(junit)
            finally:
                shutil.copy2(backup, m.target)
                assert _sha(m.target) == original_sha, f"{m.mid}: 원복이 바이트 동일하지 않다"

            red = sorted(s for s, v in outcomes.items() if v == "failed")
            if not _measured(code, outcomes):
                verdict = "측정 실패"
                failures.append(f"{m.mid}(측정 실패 exit={code})")
            elif m.scenario in red:
                verdict = "RED(검출)"
            else:
                verdict = "GREEN(생존 — 지목 시나리오가 못 잡음)"
                failures.append(m.mid)
            print(
                f"{'✓' if verdict.startswith('RED') else '✗'} {m.mid} → SCENARIO-{m.scenario}: "
                f"{verdict} · exit={code} · RED 시나리오={red} · 원복 sha256 동일"
            )
            print(f"    끊은 것: {m.why}")

    print()
    if failures:
        print(f"✗ 실패 {len(failures)}건: {failures}")
        return 1
    print(f"✓ 뮤테이션 {len(selected)}종 — 지목 시나리오 전건 RED, 원복 전건 바이트 동일.")
    print(
        "  (전건 RED는 가드의 세기일 뿐 커버리지의 증거가 아니다 — 안 본 분기는 대조표 문서 참조)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
