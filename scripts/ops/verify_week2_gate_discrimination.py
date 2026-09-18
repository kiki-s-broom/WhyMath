#!/usr/bin/env python3
"""Week 2 Gate 판정 하네스의 **변별력** 검증 — 구간을 하나씩 끊어 RED를 확인한다.

정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호
있음'으로 선언 금지"). 이 스크립트는 `tests/backend/api/test_week2_gate_wrong_answer_propagation.py`
가 재는 5구간 + 이벤트 일치 축을 **서빙 코드에서** 하나씩 끊고, 그때마다 판정이 실제로
미통과를 내는지 본다.

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
ME = BACKEND / "whymath_backend" / "api" / "me.py"
TEST = "../../tests/backend/api/test_week2_gate_wrong_answer_propagation.py"
GATE_TEST = f"{TEST}::test_week2_gate_wrong_answer_propagates_end_to_end"
CONTROL_TEST = f"{TEST}::test_misconception_step_assertion_is_discriminating"

#: (뮤테이션 이름, 대상 파일, 원본 절, 치환 절, 끊기는 구간, 돌릴 테스트)
#: 각 절은 *그 구간이 없으면 무엇이 통과하는가*의 반례다 — 추상적 경계가 아니라 실제 호출.
MUTATIONS: list[tuple[str, pathlib.Path, str, str, str, str]] = [
    (
        "M1-assessment-evidence-none",
        ME,
        "    evidence = await collect_assessment_evidence(",
        "    evidence = None  # MUTANT\n    _unused_evidence = await collect_assessment_evidence(",
        "Assessment — 증거 조립 결과를 응답에서 지운다",
        GATE_TEST,
    ),
    (
        "M2-misconception-scan-skipped",
        ME,
        "    misconception_scan_result = await _scan_attempt_misconceptions(",
        (
            "    misconception_scan_result = _NOT_SCANNED  # MUTANT\n"
            "    _unused_scan = await _scan_attempt_misconceptions("
        ),
        "Misconception — 오개념 훑기를 not_run으로 고정한다",
        GATE_TEST,
    ),
    (
        "M3-misconception-not-persisted",
        ME,
        (
            "        await apply_candidates("
            "session, user.user_id, misconception_scan_result.candidates)"
        ),
        "        pass  # MUTANT — 가설 영속 생략",
        "Misconception→LearnerState — 후보를 상태에 남기지 않는다",
        GATE_TEST,
    ),
    (
        "M4-concept-mastery-skipped",
        ME,
        "    records = await record_problem_attempt_mastery(session, evidence=evidence)",
        "    records = []  # MUTANT — 개념 숙달 전파 생략",
        "Mastery(개념) — 증거를 숙달로 옮기지 않는다",
        GATE_TEST,
    ),
    (
        "M5-skill-mastery-skipped",
        ME,
        (
            "    skill_records = await record_problem_attempt_skill_mastery("
            "session, evidence=evidence)"
        ),
        "    skill_records = []  # MUTANT — 스킬 숙달 전파 생략",
        "Mastery(스킬) — 스킬 증거를 숙달로 옮기지 않는다",
        GATE_TEST,
    ),
    (
        "M6-attempt-event-skipped",
        ME,
        "    await record_attempt_skill_event(",
        (
            "    _skip_event = True  # MUTANT — 이벤트 적재 생략\n"
            "    _unused_event = None if _skip_event else await record_attempt_skill_event("
        ),
        "이벤트 — 시도 이벤트를 남기지 않는다(상태만 바뀌고 이벤트는 없음 = KPI 2 위반)",
        GATE_TEST,
    ),
    (
        "M7-control-scan-always-candidates",
        BACKEND / "whymath_backend" / "l4" / "misconception" / "answer_signature.py",
        "    gated = apply_match_quality_gate(detect_signature_matches(signature))",
        (
            "    gated = apply_match_quality_gate(\n"
            "        detect_signature_matches(\n"
            "            ErrorSignature(claimed_lhs='(a+b)^2', claimed_rhs='a^2+b^2')\n"
            "        )\n"
            "    )  # MUTANT — 어떤 오답에도 같은 후보를 낸다"
        ),
        "대조군 — 탐지기가 아무 오답이나 잡으면(변별력 0) 대조군이 잡는가",
        CONTROL_TEST,
    ),
]


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
        for name, target, old, new, segment, test_id in MUTATIONS:
            backup = pathlib.Path(tmp) / f"{name}.bak"
            shutil.copy2(target, backup)
            original_sha = _sha(target)
            src = target.read_text(encoding="utf-8")

            # ① 치환 대상 실재 — 정확히 1건이어야 한다(0건=조용히 무주입, 2건=엉뚱한 자리).
            count = src.count(old)
            if count != 1:
                print(f"✗ {name}: 치환 대상이 {count}건이다(기대 1). 주입 하네스 결함.")
                survivors.append(f"{name} (주입 불가)")
                continue

            mutated = src.replace(old, new, 1)
            # ② 주입이 실제로 달라졌는가.
            assert mutated != src, f"{name}: 치환했는데 내용이 같다"
            target.write_text(mutated, encoding="utf-8")
            assert _sha(target) != original_sha, f"{name}: 주입 후 해시가 원본과 같다"

            try:
                code = _run_gate(test_id)
            finally:
                # ③ 원복은 바이트 백업 복원 — git 계열 금지(미커밋 작업분 소실 방지).
                shutil.copy2(backup, target)
                assert _sha(target) == original_sha, f"{name}: 원복이 바이트 동일하지 않다"

            verdict = "RED(검출)" if code != 0 else "GREEN(생존 — 변별력 없음)"
            print(f"{'✓' if code != 0 else '✗'} {name}: exit={code} {verdict}")
            print(f"    끊은 구간: {segment}")
            if code == 0:
                survivors.append(name)

    print()
    if survivors:
        print(f"✗ 생존 뮤테이션 {len(survivors)}건: {survivors}")
        print("  판정 하네스가 그 구간을 실제로 재지 않는다 — 통과를 증거로 쓸 수 없다.")
        return 1
    print(f"✓ 뮤테이션 {len(MUTATIONS)}종 전건 RED — 판정 하네스는 각 구간을 실제로 잰다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
