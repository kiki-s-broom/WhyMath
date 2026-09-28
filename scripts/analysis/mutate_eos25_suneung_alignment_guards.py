#!/usr/bin/env python3
"""EOS-25 수능 정렬 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 수능 모드 추천(`api/_next_problem_policy.py::SuneungRecommendationPolicy`)이 설명을 전달
문항에
맞추는 방식이다: 정책 의도(`resolve_policy_intent`) → 콘텐츠 재선택 **보류**(`mode_withheld`) → 정직
강등 → 정렬 선언. 설계 정본은 `docs/reviews/eos25_suneung_policy_alignment_judgment_2026-09-28.md`
(§5가 이 하네스의 실행 결과를 인용한다). 산출 필드 필수화(면제 경로 폐쇄)는 기존 하네스
`mutate_recommendation_policy_guards.py`의 M14·M25가 맡는다.

가장 위험한 형태는 **설명은 현재 개념이라고 선언한 채 콘텐츠만 옮기는 것**이다 — 정렬 판정기는
선언된
`delivered_concept`만 보므로 이 형태를 잡지 못한다(W12·I02). 그래서 단위 테스트의 세션 대역은 1차
후보
조회를 한 번만 허용하고, 실 PG 테스트는 목표 개념에 적격 문항을 실제로 심어 둔다.

규율은 선례 `scripts/analysis/mutate_eos123_attempt_hypothesis_guards.py`와 같다 — 주입 실재 단언
(앵커 1건 · 치환 후 원본과 다름) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트 동일성
단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은 pytest 종료 코드(1만 검출) · 실행마다 대상
모듈의 바이트코드 캐시 삭제 · 서빙 경로 skip은 "판정 불가".

표면이 둘이다:

- **단위**(기본): 수능 정책 오케스트레이션 테스트 + `test_me.py`의 수능 응답·근거 클래스.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL — 실제 그래프·숙달 이력으로 정책 전체. 환경변수
  `WHYMATH_DATABASE_URL`(asyncpg URL · 마이그레이션 적용된 DB)이 필요하다.

사용: `python3 scripts/analysis/mutate_eos25_suneung_alignment_guards.py [--with-integration]
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

SUNEUNG = BACKEND / "whymath_backend" / "api" / "_next_problem_policy.py"
POLICY = BACKEND / "whymath_backend" / "l2" / "recommendation_policy.py"

_TEST_ME = "../../tests/backend/api/test_me.py"
UNIT_TESTS = [
    "../../tests/backend/api/test_next_problem_policy_suneung.py",
    f"{_TEST_ME}::TestNextProblemSuneungMode",
    f"{_TEST_ME}::TestNextProblemReason",
]
INTEGRATION_TESTS = [
    "../../tests/backend/api/test_eos25_suneung_alignment_integration.py",
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


_WITHHOLD = (
    "        if intent.reselect_groups:\n"
    "            reason = demote_to_current_concept(intent.reason)\n"
    "            resolution = IntentResolution.MODE_WITHHELD\n"
)
_DELIVERED = "            problem_id=picked.problem_id,\n            reason=reason,\n"
#: 설명은 앵커(현재 개념)라고 선언한 채 콘텐츠만 목표 개념 문항으로 옮긴다 — 정렬 판정기는 선언된
#: `delivered_concept`만 보므로 이 형태를 잡지 못한다. 기본 CAT의 재선택 조회를 빌려 쓴다.
_SILENT_MOVE = (
    "            problem_id=(await __import__(\n"
    '                "whymath_backend.l2.next_problem_selection", fromlist=["x"]\n'
    "            ).load_target_candidate_rows(\n"
    "                session, theta,\n"
    "                concept_ids=[c for g in intent.reselect_groups for c in g],\n"
    "                attempted_ids=set(), excluded_ids=set(),\n"
    "            ) or [(picked.problem_id,)])[0][0],\n"
    "            reason=reason,\n"
)

MUTATIONS: list[Mutation] = [
    # ── 축 A: 결함 형태를 되살린다 ─────────────────────────────────────────────
    Mutation(
        "W01-withhold-removed",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace("if intent.reselect_groups:", "if False:"),
        "보류·강등((가) 재발 — 관계 행위가 제자리)",
    ),
    Mutation(
        "W02-posthoc-reason-restored",
        SUNEUNG,
        "        reason, resolution = intent.reason, intent.resolution\n",
        "        reason, resolution = anchor_reason, IntentResolution.DIRECT\n",
        "사후 근거(EOS-25 이전 구조)",
    ),
    Mutation(
        "W03-withheld-without-demotion",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace("demote_to_current_concept(intent.reason)", "intent.reason"),
        "보류 시 정직 강등",
    ),
    Mutation(
        "W04-target-drifts-from-delivered",
        SUNEUNG,
        "            target_concept=anchor_reason.concept_id,\n",
        "            target_concept=None,\n",
        "정렬 R2(설명≠콘텐츠)",
    ),
    Mutation(
        "W05-delivered-concept-dropped",
        SUNEUNG,
        "            delivered_concept=anchor_reason.concept_id,\n",
        "            delivered_concept=None,\n",
        "정렬 판정 입력",
    ),
    Mutation(
        "W06-no-candidate-undeclared",
        SUNEUNG,
        "                intent_resolution=IntentResolution.NO_CANDIDATE,\n",
        "                intent_resolution=None,\n",
        "부재의 정렬 선언",
    ),
    # ── 축 B: "안 했다"와 "못 했다"를 섞는다 ────────────────────────────────────
    Mutation(
        "W07-withheld-mislabeled-as-unavailable",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace("IntentResolution.MODE_WITHHELD", "IntentResolution.TARGET_UNAVAILABLE"),
        "보류≠콘텐츠 공백",
    ),
    Mutation(
        "W08-withheld-wire-value-aliased",
        POLICY,
        '    MODE_WITHHELD = "mode_withheld"\n',
        '    MODE_WITHHELD = "target_unavailable"\n',
        "응답·기록 문자열 고유성",
    ),
    Mutation(
        "W09-withhold-condition-widened-to-served",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace(
            "if intent.reselect_groups:", "if intent.resolution is IntentResolution.SERVED:"
        ),
        "보류 조건(콘텐츠 이동 여부)",
    ),
    Mutation(
        "W10-graph-budget-not-passed",
        SUNEUNG,
        "            budget=self._graph_budget,\n",
        "",
        "그래프 예산 전달",
    ),
    # ── 축 C: 콘텐츠가 옮겨진다 ─────────────────────────────────────────────────
    Mutation(
        "W11-extra-query-in-withheld-branch",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD + "            await session.execute(select(Problem))\n",
        "재선택 조회 재유입 탐지",
    ),
    Mutation(
        "W12-content-moved-silently",
        SUNEUNG,
        _DELIVERED,
        _SILENT_MOVE,
        "설명은 그대로·콘텐츠만 이동",
    ),
    # ── 서빙 경로(실 PG) ─────────────────────────────────────────────────────────
    Mutation(
        "I01-withhold-removed-on-live-path",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace("if intent.reselect_groups:", "if False:"),
        "보류·강등(실 PG)",
        True,
    ),
    Mutation(
        "I02-content-moved-silently-on-live-path",
        SUNEUNG,
        _DELIVERED,
        _SILENT_MOVE,
        "설명은 그대로·콘텐츠만 이동(실 PG)",
        True,
    ),
    Mutation(
        "I03-withheld-mislabeled-on-live-path",
        SUNEUNG,
        _WITHHOLD,
        _WITHHOLD.replace("IntentResolution.MODE_WITHHELD", "IntentResolution.REFUTED"),
        "보류≠반증(실 PG)",
        True,
    ),
]


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다."""
    for target in (SUNEUNG, POLICY):
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
                print(f"  {m.name:<46} [{surface}] axis={m.axis:<24} {verdict}")
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
