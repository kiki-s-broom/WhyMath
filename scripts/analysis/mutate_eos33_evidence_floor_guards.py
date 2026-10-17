#!/usr/bin/env python3
"""EOS-33 관계 행위 증거 요건 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 기본 CAT(`cat_v3`)이 관계 행위(선수 복귀·전진)로 콘텐츠를 옮기기 전에 요구하는 두 증거다:

- **전진 하한** — 앵커 개념의 채점 응답 3개 이상(`has_advance_evidence` ·
  `ADVANCE_EVIDENCE_MIN_RESPONSES`). 열린 후행을 **확인한 뒤에** 본다(`insufficient_evidence`).
- **선수 결손 경계** — 목표 P의 숙달이 BKT 사전값(0.3) 미만(`is_prerequisite_deficit` ·
  `PREREQUISITE_DEFICIT_CEILING`). 앵커에는 하한을 걸지 않는다.

설계 정본은 `docs/reviews/eos33_mastery_band_relational_evidence_floor_judgment_2026-09-29.md`.
EOS-124 정렬 계약 자체는 `mutate_recommendation_policy_guards.py`, 수능 정렬은
`mutate_eos25_suneung_alignment_guards.py`가 잰다(이 하네스는 그 둘이 보지 않는 축만 본다).

가장 위험한 형태는 **옛 규칙으로의 조용한 복귀**다 — 경계 상수 하나(0.3 → 0.7)나 비교 연산자
하나(`>=` → `>`)만 바뀌어도 서빙 경로는 200을 계속 내고, 해소값 분포만 조용히 달라진다. 그래서
상수·연산자·순서·운반(근거 조회기가 표본 수를 흘리는가)을 각각 따로 주입한다.

규율은 선례 `mutate_eos25_suneung_alignment_guards.py`와 같다 — 주입 실재 단언(앵커 1건 · 치환 후
원본과 다름 · 쓴 내용 재확인) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트 동일성
단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은 pytest 종료 코드(1만 검출) · 실행마다 대상
모듈의 바이트코드 캐시 삭제 · 서빙 경로 skip은 "판정 불가".

표면이 둘이다:

- **단위**(기본): 계약·정책·근거 조회기·처치 기록·수능 정책 테스트 + `test_me.py`의 근거 클래스.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL — 실제 `concept_mastery_history.sample_size`와
  그래프로 기본 CAT 정책 전체. 환경변수 `WHYMATH_DATABASE_URL`(asyncpg URL · 마이그레이션 적용된
  DB)이 필요하다.

사용: `python3 scripts/analysis/mutate_eos33_evidence_floor_guards.py [--with-integration]
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

_L2 = BACKEND / "whymath_backend" / "l2"
CONTRACT = _L2 / "recommendation_contract.py"
POLICY = _L2 / "recommendation_policy.py"
REASON = _L2 / "recommendation_reason.py"
EVIDENCE = _L2 / "recommendation_evidence.py"
TARGETS = (CONTRACT, POLICY, REASON, EVIDENCE)

_TEST_ME = "../../tests/backend/api/test_me.py"
UNIT_TESTS = [
    "../../tests/backend/l2/test_recommendation_contract.py",
    "../../tests/backend/l2/test_recommendation_policy.py",
    "../../tests/backend/l2/test_recommendation_reason.py",
    "../../tests/backend/l2/test_recommendation_evidence.py",
    "../../tests/backend/api/test_next_problem_policy_suneung.py",
    f"{_TEST_ME}::TestNextProblemReason",
]
INTEGRATION_TESTS = [
    "../../tests/backend/l2/test_eos33_evidence_floor_integration.py",
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


_FLOOR_PREDICATE = (
    "    return reason.sample_size is not None and reason.sample_size >= "
    "ADVANCE_EVIDENCE_MIN_RESPONSES\n"
)
_DEFICIT_FILTER = "        (pair for pair in measured if is_prerequisite_deficit(pair[0])),\n"
_THIN_DEMOTION = (
    "            return _demoted(anchor_reason, IntentResolution.INSUFFICIENT_EVIDENCE)\n"
)
#: `_advance_intent` docstring 끝 + 첫 그래프 읽기 — 하한을 그래프 **앞**으로 옮길 자리(F5 순서).
_ADVANCE_GRAPH_READ = (
    "    하한이 실제로 막은 이동의 수가 부풀려진다(`IntentResolution.INSUFFICIENT_EVIDENCE`).\n"
    '    """\n'
    "    successors = await _within_budget(\n"
)
_COLLECT_CARRIES = (
    "        concept_id=concept_id, mastery=mastery, confidence=confidence, "
    "sample_size=sample_size\n"
)
_PREREQ_A_SERVED = "    if weak:\n        return PolicyIntent(\n"
_PREREQ_B_SERVED = "        if blocked_reason.type is ReasonType.PREREQUISITE_GAP:\n"

MUTATIONS: list[Mutation] = [
    # ── 축 A: 전진 하한이 사라지거나 느슨해진다 ──────────────────────────────────
    Mutation(
        "F01-advance-floor-removed",
        CONTRACT,
        _FLOOR_PREDICATE,
        "    return True\n",
        "전진 하한 제거(cat_v2 복귀)",
    ),
    Mutation(
        "F02-advance-floor-off-by-one",
        CONTRACT,
        _FLOOR_PREDICATE,
        _FLOOR_PREDICATE.replace(">=", ">"),
        "경계 3(`>=`→`>`)",
    ),
    Mutation(
        "F03-advance-floor-lowered",
        CONTRACT,
        "ADVANCE_EVIDENCE_MIN_RESPONSES: Final = 3\n",
        "ADVANCE_EVIDENCE_MIN_RESPONSES: Final = 2\n",
        "하한 수치 표류(R5와 갈라짐)",
    ),
    Mutation(
        "F04-unknown-counted-as-enough",
        CONTRACT,
        _FLOOR_PREDICATE,
        "    return (reason.sample_size or 99) >= ADVANCE_EVIDENCE_MIN_RESPONSES\n",
        "모른다≠충분하다(레거시 행)",
    ),
    Mutation(
        "F05-floor-checked-before-graph",
        POLICY,
        _ADVANCE_GRAPH_READ,
        _ADVANCE_GRAPH_READ.replace(
            "    successors = await _within_budget(\n",
            "    if not has_advance_evidence(anchor_reason):\n"
            "        return _demoted(anchor_reason, IntentResolution.INSUFFICIENT_EVIDENCE)\n"
            "    successors = await _within_budget(\n",
        ),
        "하한 순서(반증·근거없음 흡수 — 작동 비율 부풀림)",
    ),
    Mutation(
        "F06-thin-advance-not-demoted",
        POLICY,
        _THIN_DEMOTION,
        "            return PolicyIntent(\n"
        "                reason=anchor_reason, resolution=IntentResolution.INSUFFICIENT_EVIDENCE\n"
        "            )\n",
        "정직 강등(전진을 말하며 제자리)",
    ),
    Mutation(
        "F07-insufficient-mislabeled-as-refuted",
        POLICY,
        _THIN_DEMOTION,
        _THIN_DEMOTION.replace("INSUFFICIENT_EVIDENCE", "REFUTED"),
        "증거 부족≠반증",
    ),
    Mutation(
        "F08-insufficient-wire-value-aliased",
        POLICY,
        '    INSUFFICIENT_EVIDENCE = "insufficient_evidence"\n',
        '    INSUFFICIENT_EVIDENCE = "refuted"\n',
        "응답·기록 문자열 고유성(Enum 별칭)",
    ),
    # ── 축 B: 선수 쪽 — 경계가 되돌아가거나 앵커 하한이 끼어든다 ─────────────────
    Mutation(
        "F09-deficit-cut-back-to-weak-ceiling",
        CONTRACT,
        "PREREQUISITE_DEFICIT_CEILING: Final = BktParameters().p_init\n",
        "PREREQUISITE_DEFICIT_CEILING: Final = 0.7\n",
        "결손 경계 상수 복귀(0.3→0.7 · 비단조 재발)",
    ),
    Mutation(
        "F10-deficit-cut-inclusive",
        CONTRACT,
        "    return mastery < PREREQUISITE_DEFICIT_CEILING\n",
        "    return mastery <= PREREQUISITE_DEFICIT_CEILING\n",
        "경계 0.30(`<`→`<=` · 사전값을 결손으로)",
    ),
    Mutation(
        "F11-policy-filter-reverted-to-weak-ceiling",
        POLICY,
        _DEFICIT_FILTER,
        "        (pair for pair in measured if pair[0] < WEAK_CONCEPT_MASTERY_CEILING),\n",
        "(가) 술어 우회(정책이 계약 술어를 안 씀)",
    ),
    Mutation(
        "F12-anchor-floor-on-prerequisite-descent",
        POLICY,
        _PREREQ_A_SERVED,
        "    if weak and has_advance_evidence(anchor_reason):\n        return PolicyIntent(\n",
        "(가) 앵커 하한 금지(막힌 학생 하강 지연)",
    ),
    Mutation(
        "F13-anchor-floor-on-blocked-successor",
        POLICY,
        _PREREQ_B_SERVED,
        "        if blocked_reason.type is ReasonType.PREREQUISITE_GAP and has_advance_evidence(\n"
        "            anchor_reason\n"
        "        ):\n",
        "(나) 앵커 하한 금지",
    ),
    Mutation(
        "F14-advance-open-check-uses-deficit-cut",
        POLICY,
        "        or mastery <= WEAK_CONCEPT_MASTERY_CEILING\n",
        "        or is_prerequisite_deficit(mastery)\n",
        "술어 뒤바뀜(후행 열림 판정에 결손 경계)",
    ),
    # ── 축 C: 운반 · 식별 ────────────────────────────────────────────────────────
    Mutation(
        "F15-collector-drops-sample-size",
        REASON,
        _COLLECT_CARRIES,
        _COLLECT_CARRIES.replace("sample_size=sample_size", "sample_size=None"),
        "근거 조회기 운반(같은 행의 표본 수)",
    ),
    Mutation(
        "F16-build-reason-drops-sample-size",
        CONTRACT,
        "        mastery=mastery,\n        sample_size=sample_size,\n    )\n",
        "        mastery=mastery,\n    )\n",
        "계약 운반(실측 근거에 표본 수)",
    ),
    Mutation(
        "F17-policy-version-not-bumped",
        EVIDENCE,
        'POLICY_VERSION_CAT: str = "cat_v3"\n',
        'POLICY_VERSION_CAT: str = "cat_v2"\n',
        "정책 식별자(소급 평가가 두 규칙을 섞음)",
    ),
    # ── 서빙 경로(실 PG) ─────────────────────────────────────────────────────────
    Mutation(
        "I01-advance-floor-removed-on-live-path",
        CONTRACT,
        _FLOOR_PREDICATE,
        "    return True\n",
        "전진 하한(실 PG)",
        True,
    ),
    Mutation(
        "I02-collector-drops-sample-size-on-live-path",
        REASON,
        _COLLECT_CARRIES,
        _COLLECT_CARRIES.replace("sample_size=sample_size", "sample_size=None"),
        "표본 수 운반(실 PG)",
        True,
    ),
    Mutation(
        "I03-deficit-cut-back-to-weak-ceiling-on-live-path",
        CONTRACT,
        "PREREQUISITE_DEFICIT_CEILING: Final = BktParameters().p_init\n",
        "PREREQUISITE_DEFICIT_CEILING: Final = 0.7\n",
        "결손 경계(실 PG)",
        True,
    ),
    Mutation(
        "I04-anchor-floor-on-prerequisite-on-live-path",
        POLICY,
        _PREREQ_A_SERVED,
        "    if weak and has_advance_evidence(anchor_reason):\n        return PolicyIntent(\n",
        "선수 쪽 앵커 하한 금지(실 PG)",
        True,
    ),
]


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다.

    크기가 같은 두 뮤테이션을 같은 1초 안에 쓰면 앞 뮤테이션의 캐시가 실행될 수 있다(2026-09-28
    main #1336 실측 · HARN-120 ⑤) — 거짓 검출과 거짓 생존이 둘 다 가능하다.
    """
    for target in TARGETS:
        for cached in (target.parent / "__pycache__").glob(f"{target.stem}.*.pyc"):
            cached.unlink()


#: 서빙 경로 표면이 skip으로 끝났다는 표식(pytest 종료 코드와 겹치지 않는 값).
SKIPPED = 97


def run_pytest(*, integration: bool) -> int:
    """대상 표면을 돌리고 **종료 코드**를 돌려준다(화면 문자열로 판정하지 않는다).

    예외 하나: 서빙 경로가 skip으로 끝나면 `SKIPPED`를 돌려준다. 통합 테스트는
    `WHYMATH_RUN_INTEGRATION` 누락·PG 미도달에서 **skip으로 exit 0**을 내므로, 이 검사가 없으면
    대조군과 뮤테이션이 둘 다 "GREEN"이 되어 하네스 전체가 공허해진다(EOS-123 선례).
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
                print(f"  {m.name:<48} [{surface}] axis={m.axis:<26} {verdict}")
                if not detected:
                    survivors.append(m.name)
            finally:
                shutil.copy2(backups[m.path], m.path)
                if m.path.read_bytes() != backups[m.path].read_bytes():
                    raise AssertionError(f"{m.name}: 원복이 바이트 동일하지 않다 — 중단")
        drop_bytecode()  # 마지막 뮤테이션의 캐시가 다음 실행에 남지 않게 한다

    print()
    if survivors:
        print(f"✗ 생존 {len(survivors)}/{len(selected)}: {', '.join(survivors)}")
        print("  생존한 뮤테이션은 '가드가 그 상태를 막지 못한다'는 뜻이다 — 보호로 계상 불가.")
        return 1
    print(f"✓ 전건 검출 {len(selected)}/{len(selected)} — 각 가드가 실제로 그 상태를 막는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
