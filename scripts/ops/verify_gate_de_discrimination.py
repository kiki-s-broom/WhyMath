#!/usr/bin/env python3
"""Phase 3 Release Gate D·E 가드의 **변별력** 검증 — 막는 상태를 주입해 RED를 확인한다 (P3-13).

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로
선언 금지"). 이 스크립트는 서빙 코드(`src/backend/whymath_backend`)에 회귀를 하나씩 주입하고, 지목한
가드가 실제로 RED를 내는지 본다. 두 묶음이다:

  census   — **이벤트 기록·귀속을 끊는 주입** 14종(C01~C09 생산자, C10~C14 P3-27 개념 채움·
             시도 귀속). 이벤트 생산자 한 곳씩을 끊고
             `tests/backend/scenarios/test_gate_d_event_role_census.py`가 그 역할에서 RED인지 본다.
             (Gate D: "기록이 끊기면 관측 가능한 실패가 나는가")
  boundary — **Core 경계 위반 주입** 2종. Core 모듈에 `if subject == "math"` 분기를 넣거나
             Core→Adapter 직접 import를 넣고, 어느 가드(`lint-imports`·`tests/infra` 경계 테스트)가
             RED를 내는지 가드별로 기록한다. (Gate E: "Core에 Math 로직 침투를 가드가 잡는가")

**주입 자체의 실재도 단언한다**(2026-09-06 규칙): 치환 대상이 정확히 1건인지, 주입 후 파일이 원본과
다른지, 원복이 바이트 동일한지(sha256)를 각각 확인한다. 주입이 조용히 실패하면 정상 파일에
대해 테스트가 돌고 "passed"가 *검출 실패*가 아니라 *검출*처럼 보인다.

원복은 `git checkout`이 아니라 **바이트 백업 복원**이다(CLAUDE.md 2026-08-10 규칙) — 트리에 미커밋
작업분이 있으면 git 계열 원복이 그것까지 되돌린다.

판정은 exit code로 낸다: 기준선이 전건 초록이고(안 그러면 뒤의 RED를 해석할 수 없다) 모든 주입이
지목 가드에서 RED면 0, 하나라도 살아남거나 측정 실패면 1. 측정 실패(수집 오류·junit 부재)는
"0건 통과"로 위장하지 않고 별도로 센다.

한계(명시): 이 스크립트는 **로컬 실행**이다. "CI에서 RED"는 PR을 열어 실 CI가 해당 스텝을 실행했음을
확인해야 성립한다 — 이 도구의 PASS를 CI RED의 증거로 읽지 않는다. 가드의 소유 잡은
`lint-imports` = CI `backend` 잡 "Import contracts" 스텝, `tests/infra` 경계 테스트 = CI
`infra-contracts` 잡 "Pytest (tests/infra)" 스텝이다.

실행(src/backend의 실 PG 필요 — CI `backend-migrations` 잡과 같은 환경):

    WHYMATH_DATABASE_URL=postgresql+asyncpg://whymath@127.0.0.1:5432/whymath \\
        python scripts/ops/verify_gate_de_discrimination.py \\
            [--suite census|boundary|all] [--only C05]
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
CENSUS_FILE = "../../tests/backend/scenarios/test_gate_d_event_role_census.py"
CENSUS_TARGET = "test_gate_d_eight_event_roles_recorded_in_a_real_student_session"

#: Gate E 경계 가드 — tests/infra의 경계 테스트 파일
#: (CI `infra-contracts` 잡이 통째로 돌리는 것의 부분집합).
_ASSESSMENT_COMMENT = (
    "    # 적재는 내부 정본(예측 5필드 포함 · 값은 항상 None)으로, " "응답은 학생 대면 정본으로.\n"
)
_LATENCY_EVENT_HEAD = (
    "        event_data=build_event_data(\n"
    "            EventType.답입력, server_latency_ms=latency_ms, "
    "mode=mode, persona=persona\n"
    "        ),\n"
    "    )\n"
)
BOUNDARY_INFRA_TESTS = (
    "tests/infra/test_eos_boundary_contract_wiring.py",
    "tests/infra/test_eos_core_boundary_probe.py",
    "tests/infra/test_core_math_vocabulary_ratchet.py",
    "tests/infra/test_eos_dependency_direction.py",
    "tests/infra/test_llm_state_authority_boundary.py",
    "tests/infra/test_eos_opaque_payload_gate.py",
)
GUARD_LINT = "lint-imports"
GUARD_INFRA_PROBE = "tests/infra/test_eos_core_boundary_probe.py"


@dataclass(frozen=True)
class Mutation:
    """회귀 1건 — 대상 파일의 원본 절(정확히 1건)을 치환하거나 끝에 덧붙인다."""

    mid: str
    suite: str  # "census" | "boundary"
    expect: str  # 지목 — census: 역할→이벤트 / boundary: 반드시 RED여야 하는 가드
    target: pathlib.Path
    old: str  # append 모드면 빈 문자열
    new: str
    why: str
    append: bool = False


MUTATIONS: tuple[Mutation, ...] = (
    # ── Gate D — 이벤트 기록을 끊는 주입(생산자 1곳씩) ───────────────────────────────────
    Mutation(
        "C01-no-diagnostic-started",
        "census",
        "learning_started→diagnostic_started",
        PKG / "api" / "me.py",
        _ASSESSMENT_COMMENT + "    session.add(Assessment.from_schema(schema))\n",
        _ASSESSMENT_COMMENT + "    pass  # MUTANT — 진단 확정이 assessment 행을 적재하지 않는다\n",
        "진단 확정이 assessment를 적재하지 않는다 → diagnostic_started 소실",
    ),
    Mutation(
        "C02-no-learner-state-basis",
        "census",
        "learning_started→learner_state_created",
        PKG / "l2" / "recommendation_evidence.py",
        "        meta[META_KEY_LEARNER_STATE_BASIS] = learner_state_basis.to_meta()\n",
        "        pass  # MUTANT — 추천이 소비한 상태의 근거를 싣지 않는다\n",
        "추천 기록이 상태 근거를 싣지 않는다 → learner_state_created 소실",
    ),
    Mutation(
        "C03-no-learning-session",
        "census",
        "concept_viewed→concept_selected",
        PKG / "l2" / "learning_session_writer.py",
        (
            "            touched = await touch_learning_session(\n"
            "                session, user_id=user_id, now=now, concept_id=concept_id\n"
            "            )\n"
            "        return touched.session_id\n"
        ),
        "            pass  # MUTANT — 학습 세션을 잇거나 열지 않는다\n        return None\n",
        "학습 세션 writer가 세션을 만들지 않는다 → concept_selected 소실(세션 결합 키도 소실)",
    ),
    Mutation(
        "C04-no-answer-latency-event",
        "census",
        "answer_submitted",
        PKG / "api" / "coach.py",
        _LATENCY_EVENT_HEAD + "    session.add(event)",
        _LATENCY_EVENT_HEAD
        + "    _ = event  # MUTANT — 답입력 이벤트를 적재하지 않는다\n    session",
        "코치 후속 턴의 응답 지연 이벤트를 적재하지 않는다 → answer_submitted 소실",
    ),
    Mutation(
        "C05-no-misconception-hypothesis",
        "census",
        "misconception_detected",
        PKG / "l4" / "misconception" / "hypothesis_store.py",
        "            session.add(\n                MisconceptionHypothesisRecord(\n",
        (
            "            (  # MUTANT — 신규 가설을 세션에 추가하지 않는다\n"
            "                MisconceptionHypothesisRecord(\n"
        ),
        "오개념 가설을 적재하지 않는다 → misconception_detected 소실",
    ),
    Mutation(
        "C06-no-demand-event",
        "census",
        "hint_requested",
        PKG / "api" / "coach.py",
        (
            "        event_data=build_event_data(EventType.힌트요청, mode=mode, persona=persona),\n"
            "    )\n"
            "    session.add(event)"
        ),
        (
            "        event_data=build_event_data(EventType.힌트요청, mode=mode, persona=persona),\n"
            "    )\n"
            "    _ = event  # MUTANT — 힌트요청 이벤트를 적재하지 않는다\n"
            "    session"
        ),
        "답 요구 발화를 힌트요청으로 적재하지 않는다 → hint_requested 소실",
    ),
    Mutation(
        "C07-no-mastery-history",
        "census",
        "mastery_updated",
        PKG / "l2" / "mastery_tracking.py",
        "    session.add(row)\n    return row\n",
        "    _ = session  # MUTANT — 숙달 측정 행을 적재하지 않는다\n    return row\n",
        "채점마다 숙달 측정 1행을 적재하지 않는다 → mastery_updated 소실",
    ),
    Mutation(
        "C08-no-recommendation-record",
        "census",
        "recommendation_generated",
        PKG / "l2" / "recommendation_evidence.py",
        "    session.add(row)\n    return row\n",
        "    _ = session  # MUTANT — 추천 처치 기록을 적재하지 않는다\n    return row\n",
        "추천 처치를 기록하지 않는다 → recommendation_generated 소실(상태 근거도 함께)",
    ),
    Mutation(
        "C09-no-problem-attempt",
        "census",
        "problem_attempted",
        PKG / "api" / "me.py",
        "    session.add(attempt)\n    await session.commit()\n    # EOS-12:",
        (
            "    _ = attempt  # MUTANT — 시도 행을 적재하지 않는다\n"
            "    await session.commit()\n    # EOS-12:"
        ),
        "채점 제출이 problem_attempt를 적재하지 않는다 → problem_attempted 소실"
        "(후속 FK 단계가 함께 깨질 수 있다)",
    ),
    # ── P3-27 — 승격한 단언(개념 채움·시도 귀속)이 끊김에서 RED인가 ─────────────────────────
    Mutation(
        "C10-no-concept-resolution",
        "census",
        "concept_viewed→concept_selected.concept_id",
        PKG / "l2" / "learning_session_writer.py",
        "        concept_id = await _resolve_concept(session, problem_id)\n",
        "        concept_id = None  # MUTANT — 문항의 대표 개념을 해석하지 않는다\n",
        "세션 writer가 문항의 개념을 해석하지 않는다 → concept_selected가 개념 없이 남는다",
    ),
    Mutation(
        "C11-no-concept-fill-on-continuation",
        "census",
        "concept_viewed→concept_selected.concept_id(NULL→값)",
        PKG / "l2" / "learning_session_writer.py",
        (
            "    if concept_id is None or row.target_concept_id is not None:\n"
            "        return False\n"
            "    row.target_concept_id = concept_id\n"
            "    return True\n"
        ),
        "    return False  # MUTANT — 이어진 세션에 개념을 채우지 않는다\n",
        "개념 없이 열린 세션(추천 조회가 첫 활동)을 뒤 활동이 채우지 못한다"
        " → concept_selected 개념 소실",
    ),
    Mutation(
        "C12-no-attempt-session-attribution",
        "census",
        "mastery_updated.session_id",
        PKG / "l2" / "learning_event_trace.py",
        '                session_id=getattr(row, "session_id", None),\n',
        "                session_id=None,  # MUTANT — 숙달 변경의 세션 귀속을 떨어뜨린다\n",
        "트레이스가 숙달 변경의 세션 귀속을 투영에서 떨어뜨린다 → mastery_updated.session_id 소실",
    ),
    Mutation(
        "C13-no-attempt-problem-attribution",
        "census",
        "mastery_updated.problem_id",
        PKG / "l2" / "learning_event_trace.py",
        '                problem_id=getattr(row, "problem_id", None),\n',
        "                problem_id=None,  # MUTANT — 숙달 변경의 문항 귀속을 떨어뜨린다\n",
        "트레이스가 숙달 변경의 문항 귀속을 투영에서 떨어뜨린다 → mastery_updated.problem_id 소실",
    ),
    Mutation(
        "C14-attempt-join-never-matches",
        "census",
        "mastery_updated.problem_id·session_id",
        PKG / "l2" / "learning_event_trace.py",
        "            & (ProblemAttempt.user_id == learner_id),\n",
        "            & (ProblemAttempt.user_id != learner_id),  # MUTANT — 시도 조인 불일치\n",
        "숙달 이력↔시도 조인이 맞지 않는다 → 귀속 두 필드가 함께 NULL",
    ),
    # ── Gate E — Core 경계 위반 주입 ─────────────────────────────────────────────────────
    Mutation(
        "B01-core-subject-literal-branch",
        "boundary",
        GUARD_INFRA_PROBE,
        PKG / "l2" / "mastery_tracking.py",
        "",
        (
            "\n\ndef _p313_injected_subject_branch(subject: str) -> bool:  # MUTANT\n"
            '    return subject == "math"  # EOS Core 안의 과목 리터럴 분기\n'
        ),
        'Core(l2)에 `if subject == "math"`류 과목 리터럴 비교를 넣는다(계획서 100 §3.7 금지 규칙)',
        append=True,
    ),
    Mutation(
        "B02-core-imports-math-adapter",
        "boundary",
        GUARD_LINT,
        PKG / "api" / "me.py",
        "",
        (
            "\nimport whymath_backend.l4.subject_adapter_math"
            "  # noqa: F401  # MUTANT — Core→Adapter 직접 import\n"
        ),
        "Core(api.me)가 수학 어댑터를 직접 import한다(Core→Adapter 역방향 의존)",
        append=True,
    ),
)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("WHYMATH_DATABASE_URL", "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")
    env["WHYMATH_RUN_INTEGRATION"] = "1"
    env["WHYMATH_DB_DISABLE_POOL"] = "1"
    return env


def _run_census(junit: pathlib.Path) -> tuple[int, dict[str, str], str]:
    """census 테스트를 돌려 (pytest exit code, 테스트별 결과, 목표 테스트의 실패 첫 줄)."""
    if junit.exists():
        junit.unlink()  # 이전 회차 결과를 이번 것으로 오독하지 않는다
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pyproject.toml",
            CENSUS_FILE,
            "-m",
            "integration",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            f"--junitxml={junit}",
        ],
        cwd=BACKEND,
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",  # 로케일 디코드 금지(HARN-19)
        timeout=900,
    )
    outcomes: dict[str, str] = {}
    reason = ""
    if junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            name = case.get("name", "")
            bad = case.find("failure")
            if bad is None:
                bad = case.find("error")
            if bad is not None:
                outcomes[name] = "failed"
                if name == CENSUS_TARGET:
                    reason = (bad.get("message") or "").strip().splitlines()[0][:220]
            elif case.find("skipped") is not None:
                outcomes[name] = "skipped"
            else:
                outcomes[name] = "passed"
    if proc.returncode not in (0, 1) or len(outcomes) != 2:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    return proc.returncode, outcomes, reason


def _census_measured(code: int, outcomes: dict[str, str]) -> bool:
    return (
        code in (0, 1)
        and len(outcomes) == 2
        and all(v in ("passed", "failed") for v in outcomes.values())
    )


def _test_file_of(classname: str) -> str:
    """junit `classname`(`tests.infra.test_x` 또는 `tests.infra.test_x.TestY`) → 파일 경로.

    `test_`로 시작하는 첫 성분까지를 모듈로 본다 — 그 뒤는 클래스명이다. 못 찾으면 원문을
    그대로 돌려줘 "파일을 특정하지 못했다"가 눈에 보이게 한다(빈 문자열로 접지 않는다).
    """
    parts = classname.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[: index + 1]) + ".py"
    return classname


def _run_boundary(junit: pathlib.Path) -> dict[str, object]:
    """Gate E 가드를 가드별로 돌린다 — lint-imports exit · tests/infra 파일별 실패 테스트."""
    result: dict[str, object] = {}
    lint = pathlib.Path(sys.executable).parent / "lint-imports"
    proc = subprocess.run(
        [str(lint)],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    result[GUARD_LINT] = proc.returncode
    if junit.exists():
        junit.unlink()
    proc2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *BOUNDARY_INFRA_TESTS,
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            f"--junitxml={junit}",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    failed_files: set[str] = set()
    total = 0
    if junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            total += 1
            if case.find("failure") is not None or case.find("error") is not None:
                failed_files.add(_test_file_of(case.get("classname") or ""))
    result["infra_exit"] = proc2.returncode
    result["infra_total"] = total
    result["infra_failed_files"] = sorted(failed_files)
    if proc2.returncode not in (0, 1) or total == 0:
        print(proc2.stdout)
        print(proc2.stderr, file=sys.stderr)
    return result


def _boundary_measured(res: dict[str, object]) -> bool:
    total = res["infra_total"]
    return (
        res["infra_exit"] in (0, 1)
        and isinstance(total, int)
        and total > 0  # 스캔 0건은 실패다
        and res[GUARD_LINT] in (0, 1)
    )


def _boundary_red(res: dict[str, object], guard: str) -> bool:
    if guard == GUARD_LINT:
        return res[GUARD_LINT] != 0
    failed = res["infra_failed_files"]
    assert isinstance(failed, list)
    return any(f.endswith(guard) or guard.endswith(f) or guard in f for f in failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=("census", "boundary", "all"), default="all")
    parser.add_argument("--only", help="이 id로 시작하는 주입만 실행(예: C05)")
    args = parser.parse_args()
    selected = [
        m
        for m in MUTATIONS
        if (args.suite in ("all", m.suite)) and (args.only is None or m.mid.startswith(args.only))
    ]
    if not selected:
        print("✗ 선택된 주입이 없다.")
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        junit = pathlib.Path(tmp) / "junit.xml"

        # 0) 기준선 — 정상 상태에서 전건 초록이어야 뒤의 RED를 해석할 수 있다.
        if any(m.suite == "census" for m in selected):
            code, base, _ = _run_census(junit)
            print(f"BASELINE[census] exit={code} outcomes={dict(sorted(base.items()))}")
            if not _census_measured(code, base) or any(v != "passed" for v in base.values()):
                print("✗ census 기준선이 전건 통과가 아니다(또는 측정 실패) — 해석 불가.")
                return 1
        if any(m.suite == "boundary" for m in selected):
            bres = _run_boundary(junit)
            print(f"BASELINE[boundary] {bres}")
            if not _boundary_measured(bres) or bres[GUARD_LINT] != 0 or bres["infra_exit"] != 0:
                print("✗ boundary 기준선이 초록이 아니다(또는 측정 실패) — 해석 불가.")
                return 1

        for m in selected:
            backup = pathlib.Path(tmp) / f"{m.mid}.bak"
            shutil.copy2(m.target, backup)
            original_sha = _sha(m.target)
            src = m.target.read_text(encoding="utf-8")
            if m.append:
                mutated = src + m.new
            else:
                count = src.count(m.old)
                if count != 1:
                    print(f"✗ {m.mid}: 치환 대상이 {count}건이다(기대 1) — 주입 하네스 결함.")
                    failures.append(f"{m.mid}(주입 불가)")
                    continue
                mutated = src.replace(m.old, m.new, 1)
            if mutated == src:
                print(f"✗ {m.mid}: 주입했는데 내용이 같다 — 주입 하네스 결함.")
                failures.append(f"{m.mid}(주입 무효)")
                continue
            m.target.write_text(mutated, encoding="utf-8")
            if _sha(m.target) == original_sha:
                m.target.write_bytes(backup.read_bytes())
                print(f"✗ {m.mid}: 주입 후 해시가 원본과 같다.")
                failures.append(f"{m.mid}(주입 무효)")
                continue
            try:
                if m.suite == "census":
                    code, outcomes, reason = _run_census(junit)
                else:
                    bres = _run_boundary(junit)
            finally:
                shutil.copy2(backup, m.target)
            if _sha(m.target) != original_sha:
                print(f"✗ {m.mid}: 원복이 바이트 동일하지 않다 — 중단.")
                return 1

            if m.suite == "census":
                if not _census_measured(code, outcomes):
                    verdict = "측정 실패"
                    failures.append(f"{m.mid}(측정 실패 exit={code})")
                elif outcomes.get(CENSUS_TARGET) == "failed":
                    verdict = "RED(검출)"
                else:
                    verdict = "GREEN(생존 — 기록을 끊었는데 census가 못 잡음)"
                    failures.append(m.mid)
                print(
                    f"{'✓' if verdict.startswith('RED') else '✗'} {m.mid} → {m.expect}: {verdict}"
                    f" · exit={code} · 원복 sha256 동일"
                )
                if reason:
                    print(f"    관측된 실패: {reason}")
            else:
                if not _boundary_measured(bres):
                    verdict = "측정 실패"
                    failures.append(f"{m.mid}(측정 실패)")
                elif _boundary_red(bres, m.expect):
                    verdict = f"RED(검출 — 지목 가드 {m.expect})"
                else:
                    verdict = f"GREEN(생존 — 지목 가드 {m.expect}가 못 잡음)"
                    failures.append(m.mid)
                print(f"{'✓' if verdict.startswith('RED') else '✗'} {m.mid}: {verdict}")
                print(
                    f"    가드별 결과: lint-imports exit={bres[GUARD_LINT]} · tests/infra exit="
                    f"{bres['infra_exit']}({bres['infra_total']}건)"
                    f" · 실패 파일={bres['infra_failed_files']}"
                )
            print(f"    끊은 것: {m.why}")

    print()
    if failures:
        print(f"✗ 실패 {len(failures)}건: {failures}")
        return 1
    print("✓ 선택한 주입 전건 지목 가드에서 RED, 원복 전건 바이트 동일.")
    print(
        "  (전건 RED는 가드의 세기일 뿐 커버리지의 증거가 아니다 — 안 넣은 분기는 판정 문서 참조)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
