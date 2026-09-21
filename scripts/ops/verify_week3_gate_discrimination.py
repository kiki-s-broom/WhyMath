#!/usr/bin/env python3
"""Week 3 Gate 판정 하네스의 **변별력** 검증 — 화살표를 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호
있음'으로 선언 금지"). 이 스크립트는 `tests/backend/api/test_week3_gate_remediation_loop.py`가
재는 **다섯 화살표**를 서빙 코드에서 하나씩 끊고, 그때마다 판정이 실제로 미통과를 내는지 본다.

*마디*가 아니라 *화살표*를 끊는 것이 핵심이다 — 마디의 산출물은 앞 마디와 무관하게도 나올 수
있고(예: 코치는 언제나 무언가 말한다), 그 경우 판정은 "이어졌다"가 아니라 "둘 다 존재한다"를
잰 것이 된다.

**주입 자체의 실재도 단언한다**(2026-09-06 규칙): 치환 대상이 정확히 1건인지, 치환 후 파일이
원본과 다른지, 원복이 바이트 동일한지를 각각 확인한다. 주입이 조용히 실패하면 정상 파일에
대해 테스트가 돌고 "passed"가 *검출 실패*가 아니라 *검출*처럼 보인다.

원복은 `git checkout`이 아니라 **바이트 백업 복원**이다(CLAUDE.md 2026-08-10 규칙) — 이 트리에는
아직 커밋되지 않은 작업분이 있고 git 계열 원복은 그것까지 되돌린다.

판정: 전 뮤테이션이 RED면 exit 0, 하나라도 살아남으면 exit 1.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "src" / "backend"
PKG = BACKEND / "whymath_backend"
ME = PKG / "api" / "me.py"
COACH = PKG / "api" / "coach.py"
SELECTION = PKG / "l2" / "next_problem_selection.py"
REASON = PKG / "l2" / "recommendation_reason.py"
INTERVENE = PKG / "l4" / "misconception" / "intervene.py"

TEST = "../../tests/backend/api/test_week3_gate_remediation_loop.py"
GATE_TEST = f"{TEST}::test_week3_gate_remediation_loop_is_automatic"
CONTROL_TEST = f"{TEST}::test_remediation_content_requires_a_prior_wrong_answer"

#: (이름, 대상 파일, 원본 절, 치환 절, 끊는 화살표, 돌릴 테스트)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str, str]] = [
    (
        "M1-misconception-scan-skipped",
        ME,
        "    misconception_scan_result = await _scan_attempt_misconceptions(",
        (
            "    misconception_scan_result = _NOT_SCANNED  # MUTANT\n"
            "    _unused_scan = await _scan_attempt_misconceptions("
        ),
        "오답 → Misconception — 답안을 오개념으로 읽지 않는다",
        GATE_TEST,
    ),
    (
        "M2-hypothesis-not-persisted",
        ME,
        (
            "        await apply_candidates("
            "session, user.user_id, misconception_scan_result.candidates)"
        ),
        "        pass  # MUTANT — 가설 영속 생략",
        "Misconception → 교정 콘텐츠 — 후보를 남기지 않아 코치가 읽을 것이 없다",
        GATE_TEST,
    ),
    (
        "M3-coach-ignores-hypotheses",
        COACH,
        "    return select_intervention_from_hypotheses(active_hypotheses) or fallback",
        "    return fallback  # MUTANT — 누적 가설을 읽지 않고 단일 턴 매치만 쓴다",
        "Misconception → 교정 콘텐츠 — 코치가 영속된 가설을 읽지 않는다(중립 발화면 개입 0)",
        GATE_TEST,
    ),
    (
        "M4-hint-event-not-logged",
        COACH,
        (
            "    await _log_hint_event(\n"
            "        session,\n"
            "        user_id=user.user_id,\n"
            "        problem_id=body.problem_id,\n"
            "        attempt_id=dialogue.attempt_id,\n"
            "        hint_level=decision.hint_level,"
        ),
        (
            "    _skip_hint_log = True  # MUTANT — 세션 생성 턴의 힌트 적재 생략\n"
            "    _unused_hint = None if _skip_hint_log else await _log_hint_event(\n"
            "        session,\n"
            "        user_id=user.user_id,\n"
            "        problem_id=body.problem_id,\n"
            "        attempt_id=dialogue.attempt_id,\n"
            "        hint_level=decision.hint_level,"
        ),
        "교정 콘텐츠 → AI Hint — 사다리 직전값의 *적재*를 끊는다(다음 턴이 읽을 것이 없다)",
        GATE_TEST,
    ),
    (
        "M5-prev-hint-not-recovered",
        COACH,
        (
            "    server_prev_hint = await _prev_hint_level_for(\n"
            "        session, user_id=user.user_id, problem_id=dialogue.problem_id\n"
            "    )"
        ),
        (
            "    server_prev_hint = None  # MUTANT — 직전 단계를 되찾지 않는다\n"
            "    _unused_prev = await _prev_hint_level_for(\n"
            "        session, user_id=user.user_id, problem_id=dialogue.problem_id\n"
            "    )"
        ),
        "교정 콘텐츠 → AI Hint — 적재는 하되 *읽기*를 끊는다(사다리가 제자리)",
        GATE_TEST,
    ),
    (
        "M6-attempted-not-excluded",
        SELECTION,
        (
            "    if attempted_ids:\n"
            "        stmt = stmt.where(Problem.problem_id.notin_(attempted_ids))"
        ),
        (
            "    if False:  # MUTANT — 시도 이력 제외 생략\n"
            "        stmt = stmt.where(Problem.problem_id.notin_(attempted_ids))"
        ),
        "AI Hint → 새 문제 — 방금 틀린 문항을 다시 낸다(추천이 시도를 안 본다)",
        GATE_TEST,
    ),
    (
        "M7-reason-mastery-dropped",
        REASON,
        "    return build_reason(concept_id=concept_id, mastery=mastery, confidence=confidence)",
        (
            "    return build_reason(\n"
            "        concept_id=concept_id, mastery=None, confidence=confidence\n"
            "    )  # MUTANT — 근거에서 실측 숙달을 지운다"
        ),
        "AI Hint → 새 문제 — 추천 근거가 그 오답이 쓴 값을 인용하지 못한다",
        GATE_TEST,
    ),
    (
        "M8-control-intervention-always",
        INTERVENE,
        (
            "    focus = select_focus(hypotheses, epsilon=epsilon, rng=rng)\n"
            "    if focus is None:\n"
            "        return None"
        ),
        (
            "    focus = select_focus(hypotheses, epsilon=epsilon, rng=rng) or _MUTANT_FOCUS\n"
            "    if focus is None:  # MUTANT — 가설이 없어도 개입을 만들어 낸다\n"
            "        return None"
        ),
        "대조군 — 개입이 가설과 무관하게 항상 나오면(변별력 0) 대조군이 잡는가",
        CONTROL_TEST,
    ),
]

#: M8이 필요로 하는 상수 — 가설이 0건이어도 개입을 만들어 내는 가짜 focus.
#: 모듈 *끝*에 덧붙인다(함수 본문은 호출 시점에 평가되므로 정의 순서가 문제되지 않는다).
_M8_MUTANT_FOCUS_DEF = (
    "\n\n_MUTANT_FOCUS = MisconceptionHypothesis(  # MUTANT\n"
    '    misconception_id="distribution-over-power",\n'
    "    confidence=0.9,\n"
    "    turns_since_evidence=0,\n"
    "    evidence_count=1,\n"
    ")\n"
)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_gate(test_id: str) -> int:
    """판정 하네스를 돌리고 **exit code**를 돌려준다(출력 문자열로 판정하지 않는다)."""
    env = dict(os.environ)
    env.setdefault("WHYMATH_DATABASE_URL", "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath")
    env["WHYMATH_RUN_INTEGRATION"] = "1"
    env["WHYMATH_DB_DISABLE_POOL"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pyproject.toml",
            "--rootdir=.",
            test_id,
            "-m",
            "integration",
            "-p",
            "no:randomly",
            "-q",
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        # 로케일 인코딩 디코드 금지(HARN-19) — 한국어 Windows(cp949)에서 붕괴한다.
        encoding="utf-8",
        timeout=900,
    )
    return proc.returncode


def _apply(name: str, src: str, old: str, new: str) -> str | None:
    """치환 1건을 적용한다. 대상이 정확히 1건이 아니면 None(주입 하네스 결함)."""
    count = src.count(old)
    if count != 1:
        print(f"✗ {name}: 치환 대상이 {count}건이다(기대 1). 주입 하네스 결함.")
        return None
    mutated = src.replace(old, new, 1)
    if name.startswith("M8"):
        # 가짜 focus 상수를 모듈 끝이 아니라 *정의 시점보다 앞*에 두면 import 순서에 걸린다 —
        # 모듈 말미에 두고 함수 실행 시점에 해소되게 한다(함수 본문은 호출 때 평가된다).
        mutated = mutated + _M8_MUTANT_FOCUS_DEF
    return mutated


def main() -> int:
    # 0) 기준선 — 뮤테이션 전 정상 상태에서 판정이 통과하는가.
    #    이게 없으면 뒤의 RED가 뮤테이션 때문인지 환경 때문인지 구별할 수 없다.
    baseline = _run_gate(TEST)
    print(f"BASELINE exit={baseline} (기대 0 — 정상 상태에서 판정 통과)")
    if baseline != 0:
        print("✗ 기준선이 이미 실패다 — 뮤테이션 결과를 해석할 수 없다.")
        return 1

    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, target, old, new, arrow, test_id in MUTATIONS:
            backup = pathlib.Path(tmp) / f"{name}.bak"
            shutil.copy2(target, backup)
            original_sha = _sha(target)
            src = target.read_text(encoding="utf-8")

            mutated = _apply(name, src, old, new)
            if mutated is None:
                survivors.append(f"{name} (주입 불가)")
                continue
            assert mutated != src, f"{name}: 치환했는데 내용이 같다"
            target.write_text(mutated, encoding="utf-8")
            assert _sha(target) != original_sha, f"{name}: 주입 후 해시가 원본과 같다"

            try:
                code = _run_gate(test_id)
            finally:
                shutil.copy2(backup, target)
                assert _sha(target) == original_sha, f"{name}: 원복이 바이트 동일하지 않다"

            verdict = "RED(검출)" if code != 0 else "GREEN(생존 — 변별력 없음)"
            print(f"{'✓' if code != 0 else '✗'} {name}: exit={code} {verdict}")
            print(f"    끊은 화살표: {arrow}")
            if code == 0:
                survivors.append(name)

    print()
    if survivors:
        print(f"✗ 생존 뮤테이션 {len(survivors)}건: {survivors}")
        print("  판정 하네스가 그 화살표를 실제로 재지 않는다 — 통과를 증거로 쓸 수 없다.")
        return 1
    print(f"✓ 뮤테이션 {len(MUTATIONS)}종 전건 RED — 판정 하네스는 각 화살표를 실제로 잰다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
