#!/usr/bin/env python3
"""EOS-31 수능 출제 범위 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 수능 모드의 출제 범위 판정이다: 정의(`l6/suneung/scope.py`) → 게이트 ②-c(`gating.py`) → SQL
사전필터(`api/_next_problem_policy.py::suneung_scope_clause`) → 후보 성취기준 코드 주입 → 정책 버전.
설계 정본은 `docs/reviews/eos31_suneung_scope_judgment_2026-10-01.md`다.

이 가드가 막는 결함은 **눈에 안 띄는 방향**이 많다 — 범위 판정이 느슨해져도 응답은 200이고 문항도
나간다(초·중 문항이 고3에게 나갈 뿐이다). 그래서 정상 입력의 초록은 보호의 증거가 아니고, 아래
뮤테이션
각각이 해당 가드를 RED로 만드는지만이 증거다.

규율은 선례 `mutate_eos25_suneung_alignment_guards.py`와 같다 — 주입 실재 단언(앵커 1건 · 치환 후
원본과
다름) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트 동일성 단언 · 중단(시그널)에도
원복 ·
성공 방향 대조군 · 판정은 pytest 종료 코드(1만 검출) · 실행마다 바이트코드 캐시 삭제 · 서빙 경로
skip은
"판정 불가".

표면이 둘이다:

- **단위**(기본): L6 수능 게이트·범위 정의 + 정책 오케스트레이션 + `/v1/gating/suneung` + 정책 버전.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL — SQL 절↔파이썬 게이트 일치, 후보 풀 소멸 방지.
  환경변수 `WHYMATH_DATABASE_URL`(asyncpg URL · 마이그레이션만 적용된 **빈** DB)이 필요하다.

사용: `python3 scripts/analysis/mutate_eos31_suneung_scope_guards.py [--with-integration]
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
PKG = BACKEND / "whymath_backend"

SCOPE = PKG / "l6" / "suneung" / "scope.py"
GATING = PKG / "l6" / "suneung" / "gating.py"
POLICY = PKG / "api" / "_next_problem_policy.py"
API_GATING = PKG / "api" / "gating.py"
EVIDENCE = PKG / "l2" / "recommendation_evidence.py"

_TESTS = "../../tests/backend"
UNIT_TESTS = [
    f"{_TESTS}/l6/suneung",
    f"{_TESTS}/api/test_next_problem_policy_suneung.py",
    f"{_TESTS}/api/test_gating.py::TestSuneung",
    f"{_TESTS}/api/test_me.py::TestNextProblemSuneungMode",
    f"{_TESTS}/l2/test_recommendation_evidence.py::TestCandidatesAndPolicyVersion",
]
INTEGRATION_TESTS = [
    f"{_TESTS}/api/test_eos31_suneung_scope_integration.py",
    f"{_TESTS}/api/test_eos25_suneung_alignment_integration.py",
]
SKIPPED = -1


@dataclass(frozen=True)
class Mutation:
    """뮤테이션 1건 — 어느 파일의 어느 절들을 무엇으로 바꾸는가 + 어느 표면이 RED여야 하는가."""

    name: str
    path: Path
    edits: tuple[tuple[str, str], ...]  # (old, new) — 각 old는 파일에서 정확히 1건이어야 한다
    axis: str  # 이 뮤테이션이 검사하는 축(보고용)
    integration: bool = False  # True면 실 PG 서빙 경로 표면에서 판정한다


_GATE_CHECK = (
    "    if suneung_scope_verdict(problem) is not ScopeVerdict.IN_SCOPE:\n        return False\n"
)
_GATE_RETURN = "    return is_exam_signal or has_signature or meets_fit"
_CLAUSE_CURRICULUM = "        Problem.curriculum_version == SUNEUNG_SCOPE.curriculum.value,\n"
_INJECT = (
    "                candidate.achievement_standard_codes = sorted(\n"
    "                    codes_by_problem[candidate.problem_id]\n"
    "                )\n"
)

MUTATIONS: list[Mutation] = [
    # ── 축 A: 범위 정의(L6) ────────────────────────────────────────────────────
    Mutation(
        "S01-unknown-collapsed-into-out",
        SCOPE,
        (("    if not codes:\n        return ScopeVerdict.UNKNOWN\n", ""),),
        "모른다 ≠ 아니다(세 값 판정)",
    ),
    Mutation(
        "S02-curriculum-check-removed",
        SCOPE,
        (
            (
                "    if _normalized_curriculum(problem) != scope.curriculum.value:\n"
                "        return ScopeVerdict.OUT_OF_SCOPE\n",
                "",
            ),
        ),
        "같은 접두어·다른 개정",
    ),
    Mutation(
        "S03-any-became-all",
        SCOPE,
        (
            (
                "    if any(code_in_scope(code, scope) for code in codes):",
                "    if all(code_in_scope(code, scope) for code in codes):",
            ),
        ),
        "'하나라도' 의미(브리지 문항)",
    ),
    Mutation(
        "S04-prefix-became-substring",
        SCOPE,
        (
            (
                "    return code.startswith(scope.code_startswith_patterns())",
                "    return any(p in code for p in scope.code_startswith_patterns())",
            ),
        ),
        "접두어 앵커(부분 일치 금지)",
    ),
    Mutation(
        "S05-scope-widened-to-middle-school",
        SCOPE,
        (
            (
                '    code_prefixes=("12대수", "12미적Ⅰ", "12확통"),',
                '    code_prefixes=("12대수", "12미적Ⅰ", "12확통", "9수"),',
            ),
        ),
        "범위 확대(초·중 유입)",
    ),
    Mutation(
        "S06-calculus-prefix-lets-calculus2-in",
        SCOPE,
        (
            (
                '    code_prefixes=("12대수", "12미적Ⅰ", "12확통"),',
                '    code_prefixes=("12대수", "12미적", "12확통"),',
            ),
        ),
        "진로 선택 과목(미적분Ⅱ) 유입",
    ),
    # ── 축 B: 게이트 ②-c ───────────────────────────────────────────────────────
    Mutation(
        "G01-scope-gate-removed",
        GATING,
        ((_GATE_CHECK, ""),),
        "원 결함 재현(게이트가 범위를 안 본다)",
    ),
    Mutation(
        "G02-unknown-passes",
        GATING,
        (
            (
                "suneung_scope_verdict(problem) is not ScopeVerdict.IN_SCOPE",
                "suneung_scope_verdict(problem) is ScopeVerdict.OUT_OF_SCOPE",
            ),
        ),
        "fail-closed(범위를 모르는 문항 통과)",
    ),
    Mutation(
        "G03-scope-demoted-to-signal",
        GATING,
        (
            (_GATE_CHECK, ""),
            (
                _GATE_RETURN,
                "    return (\n"
                "        is_exam_signal\n"
                "        or has_signature\n"
                "        or meets_fit\n"
                "        or suneung_scope_verdict(problem) is ScopeVerdict.IN_SCOPE\n"
                "    )",
            ),
        ),
        "범위는 선결 조건(AND)이지 신호(OR)가 아니다",
    ),
    # ── 축 C: SQL 사전필터 ─────────────────────────────────────────────────────
    Mutation(
        "P01-prefilter-scope-clause-dropped",
        POLICY,
        (("            suneung_scope_clause(),\n", ""),),
        "후보 풀 소멸 방지(사전필터가 범위를 모른다)",
        integration=True,
    ),
    Mutation(
        "P02-prefilter-curriculum-dropped",
        POLICY,
        ((_CLAUSE_CURRICULUM, "        true(),\n"),),
        "SQL↔파이썬 일치(개정 조건)",
        integration=True,
    ),
    Mutation(
        "P03-prefilter-prefix-became-contains",
        POLICY,
        (
            (
                "code_column.startswith(pattern, autoescape=True)",
                "code_column.contains(pattern, autoescape=True)",
            ),
        ),
        "SQL↔파이썬 일치(접두어 앵커)",
        integration=True,
    ),
    Mutation(
        "P04-prefilter-only-first-prefix",
        POLICY,
        (
            (
                "                        for pattern in SUNEUNG_SCOPE.code_startswith_patterns()\n",
                "                        for pattern in "
                "SUNEUNG_SCOPE.code_startswith_patterns()[:1]\n",
            ),
        ),
        "SQL↔파이썬 일치(접두어 목록 전체)",
        integration=True,
    ),
    # ── 축 D: 주입·배선 ────────────────────────────────────────────────────────
    Mutation(
        "I01-policy-injection-dropped",
        POLICY,
        ((_INJECT, "                pass\n"),),
        "후보 코드 주입(빠지면 후보 소멸)",
    ),
    Mutation(
        "I02-gating-endpoint-without-codes",
        API_GATING,
        (("    candidates: SuneungCandidatesDep,", "    candidates: CandidatesDep,"),),
        "/v1/gating/suneung 코드 주입(조용한 빈 결과)",
    ),
    Mutation(
        "I03-gating-dependency-skips-injection",
        API_GATING,
        (
            (
                "    candidates = await _fetch_candidates(session)\n"
                "    await _inject_achievement_codes(session, candidates)\n"
                "    return candidates\n\n\nSuneungCandidatesDep",
                "    candidates = await _fetch_candidates(session)\n"
                "    return candidates\n\n\nSuneungCandidatesDep",
            ),
        ),
        "수능 의존성의 주입 호출",
    ),
    # ── 축 E: 정책 버전 ────────────────────────────────────────────────────────
    Mutation(
        "V01-policy-version-not-bumped",
        EVIDENCE,
        (
            (
                'POLICY_VERSION_SUNEUNG: str = "suneung_v2"',
                'POLICY_VERSION_SUNEUNG: str = "suneung_v1"',
            ),
        ),
        "후보 규칙이 바뀌면 REC-11 식별자를 올린다",
    ),
]


def drop_bytecode() -> None:
    """뮤테이션 대상 모듈의 바이트코드 캐시를 지운다 — 같은 초 안의 수정이 옛 캐시로 가려지지
    않게."""
    for path in {m.path for m in MUTATIONS}:
        cache = path.parent / "__pycache__"
        if cache.is_dir():
            for pyc in cache.glob(f"{path.stem}.*.pyc"):
                pyc.unlink()


def run_pytest(*, integration: bool) -> int:
    """대상 표면을 돌리고 **종료 코드**를 돌려준다(화면 문자열로 판정하지 않는다).

    서빙 경로가 skip으로 끝나면 `SKIPPED`를 돌려준다 — 통합 테스트는 `WHYMATH_RUN_INTEGRATION`
    누락·PG
    미도달에서 **skip으로 exit 0**을 내므로, 이 검사가 없으면 대조군과 뮤테이션이 둘 다 "GREEN"이
    되어
    하네스 전체가 공허해진다(EOS-123 선례).
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
    # 하므로
    # 시간 상한을 건다.
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
    """종료 코드 → 판정. **1만 검출**이다 — 수집 오류(2)·사용 오류(4)·테스트 0건(5)·skip은 "가드가
    막았다"가 아니라 "판정하지 못했다"이므로 검출로 세지 않는다."""
    if code == 1:
        return "RED(검출)"
    if code == 0:
        return "GREEN(생존)"
    return f"판정 불가(exit={code})"


def apply_mutation(m: Mutation) -> None:
    """치환 + **적용 실재 단언** — 각 앵커가 1건이고 결과가 원본과 다름을 쓰기 전에 확인한다."""
    src = m.path.read_text(encoding="utf-8")
    mutated = src
    for old, new in m.edits:
        count = mutated.count(old)
        if count != 1:
            raise AssertionError(
                f"{m.name}: 앵커 {count}건(1건이어야 한다) — 하네스가 대상을 놓쳤다"
            )
        mutated = mutated.replace(old, new)
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
        print(
            "✗ --with-integration에는 WHYMATH_DATABASE_URL(마이그레이션만 적용된 빈 DB)이 필요하다"
        )
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
        # 시작 시점의 원본 바이트를 **메모리에** 잡아 둔다 — 원복 검증이 백업 파일끼리의 비교가 되면
        # 백업이 잘못 만들어졌을 때 검증도 같이 통과한다(순환 검증).
        originals: dict[Path, bytes] = {}
        for path in {m.path for m in selected}:
            # 백업 이름은 저장소 상대경로로 유일하게 만든다 — `l6/suneung/gating.py`와
            # `api/gating.py`처럼 파일명이 같은 대상이 서로의 백업을 덮어쓴 사고(2026-10-01)가
            # 있었다.
            backup = Path(tmp) / str(path.relative_to(REPO)).replace(os.sep, "__")
            shutil.copy2(path, backup)  # git이 아니라 파일 복사로 원복한다(2026-08-10 규율)
            backups[path] = backup
            originals[path] = path.read_bytes()
        if len({b.name for b in backups.values()}) != len(backups):
            raise AssertionError("백업 파일명이 겹친다 — 원복이 다른 파일을 덮어쓴다")

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
                surface = "서빙" if m.integration else "단위"
                print(f"  {m.name:<42} [{surface}] axis={m.axis:<34} {verdict}")
                if code != 1:
                    survivors.append(m.name)
            finally:
                shutil.copy2(backups[m.path], m.path)
                if m.path.read_bytes() != originals[m.path]:
                    raise AssertionError(f"{m.name}: 원복이 시작 시점 바이트와 다르다 — 중단")

    print()
    if survivors:
        print(f"✗ 생존 {len(survivors)}/{len(selected)}: {', '.join(survivors)}")
        print("  생존한 뮤테이션은 '가드가 그 상태를 막지 못한다'는 뜻이다 — 보호로 계상 불가.")
        return 1
    print(f"✓ 전건 검출 {len(selected)}/{len(selected)} — 각 가드가 실제로 그 상태를 막는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
