#!/usr/bin/env python3
"""EOS-25 수능 정렬 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 수능 모드 추천(`api/_next_problem_policy.py::SuneungRecommendationPolicy`)이 설명과 콘텐츠를
맞추는 방식이다: 정책 의도(`resolve_policy_intent`) → 수능 정렬 재선택(`_select_aligned` ·
`load_suneung_target_candidates`) → 정직 강등 → 정렬 선언. 설계 정본은
`docs/reviews/eos25_suneung_policy_alignment_judgment_2026-09-28.md`(§8이 이 하네스의 실행 결과를
인용한다). 산출 필드 필수화(면제 경로 폐쇄)는 기존 하네스
`mutate_recommendation_policy_guards.py`의 M14·M25가 맡는다.

규율은 선례 `scripts/analysis/mutate_eos123_attempt_hypothesis_guards.py`와 같다 — 주입 실재 단언
(앵커 1건 · 치환 후 원본과 다름) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트 동일성
단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은 pytest 종료 코드(1만 검출) · 실행마다 대상
모듈의 바이트코드 캐시 삭제 · 서빙 경로 skip은 "판정 불가".

표면이 둘이다:

- **단위**(기본): 수능 정책 오케스트레이션 테스트 + `test_me.py`의 수능 응답 클래스 + 정책 버전
  동결. DB 없이 오케스트레이션·배선을 잰다(조회는 전부 대역).
- **서빙 경로**(`--with-integration`): 실 PostgreSQL — 수능 목표 후보 SQL과 정책 전체. 환경변수
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
EVIDENCE = BACKEND / "whymath_backend" / "l2" / "recommendation_evidence.py"

_TEST_ME = "../../tests/backend/api/test_me.py"
UNIT_TESTS = [
    "../../tests/backend/api/test_next_problem_policy_suneung.py",
    f"{_TEST_ME}::TestNextProblemSuneungMode",
    f"{_TEST_ME}::TestNextProblemReason",
    "../../tests/backend/l2/test_recommendation_evidence.py",
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


_RESELECT_BRANCH = (
    "        if intent.reselect_groups:\n            aligned = await self._select_aligned("
)
_RESELECT_PICK = (
    "            index = recommend_suneung_index(theta, picked, persona, extra_weights=weights)\n"
)
#: 진실 게이트 없이 정보량 × 추가 가중만으로 고르는 선택 — 기본 CAT 재선택의 모양이다.
_UNGATED_PICK = (
    '            index = __import__("whymath_backend.l2.irt", fromlist=["x"]).select_weighted_item('
    "theta, [IrtItem(difficulty=resolve_item_difficulty_b(p.irt_difficulty_b, "
    "p.difficulty_overall) or 0.0) for p in picked], weights=weights)\n"
)
_TARGET_QUERY_ARGS = (
    "            attempted_ids=attempted_ids,\n"
    "            excluded_ids=excluded_ids,\n"
    "        )\n"
    "        for group in groups:"
)
_TARGET_WHERE = (
    "            *suneung_pool_conditions(persona),\n"
    "            ProblemConcept.role == ConceptRole.PRIMARY,\n"
)

MUTATIONS: list[Mutation] = [
    # ── 축 A: 결함 형태를 되살린다 ─────────────────────────────────────────────
    Mutation(
        "S01-reselection-skipped",
        SUNEUNG,
        _RESELECT_BRANCH,
        _RESELECT_BRANCH.replace("if intent.reselect_groups:", "if False:"),
        "정렬 재선택((가) 재발)",
    ),
    Mutation(
        "S02-posthoc-reason-restored",
        SUNEUNG,
        "        reason, resolution = intent.reason, intent.resolution\n",
        "        reason, resolution = anchor_reason, IntentResolution.DIRECT\n",
        "사후 근거(EOS-25 이전 구조)",
    ),
    Mutation(
        "S03-demotion-skipped",
        SUNEUNG,
        "                reason = demote_to_current_concept(intent.reason)\n",
        "                reason = intent.reason\n",
        "정직 강등",
    ),
    Mutation(
        "S04-unavailable-mislabeled",
        SUNEUNG,
        "                resolution = IntentResolution.TARGET_UNAVAILABLE\n",
        "                resolution = IntentResolution.REFUTED\n",
        "강등 사유(콘텐츠 공백≠반증)",
    ),
    Mutation(
        "S05-delivered-concept-dropped",
        SUNEUNG,
        "            delivered_concept=delivery.concept_id,\n",
        "            delivered_concept=None,\n",
        "정렬 판정 입력",
    ),
    Mutation(
        "S06-no-candidate-undeclared",
        SUNEUNG,
        "                intent_resolution=IntentResolution.NO_CANDIDATE,\n",
        "                intent_resolution=None,\n",
        "부재의 정렬 선언",
    ),
    # ── 축 B: 재선택이 수능 모드를 벗어난다 ────────────────────────────────────
    Mutation(
        "S07-truth-gate-bypassed-on-reselection",
        SUNEUNG,
        _RESELECT_PICK,
        _UNGATED_PICK,
        "재선택 진실 게이트",
    ),
    Mutation(
        "S08-persona-dropped-from-reselection-gate",
        SUNEUNG,
        _RESELECT_PICK,
        _RESELECT_PICK.replace("picked, persona,", "picked, Persona.A_일반고고3,"),
        "재선택 게이트 페르소나",
    ),
    Mutation(
        "S09-persona-dropped-from-reselection-query",
        SUNEUNG,
        "            persona=persona,\n            concept_ids=[concept for group in groups",
        "            persona=Persona.A_일반고고3,\n"
        "            concept_ids=[concept for group in groups",
        "재선택 조회 페르소나",
    ),
    Mutation(
        "S10-gated-group-stops-search",
        SUNEUNG,
        "            if index is None:\n                continue\n",
        "            if index is None:\n                return None\n",
        "게이트에 막힌 묶음 건너뛰기",
    ),
    Mutation(
        "S11-empty-group-stops-search",
        SUNEUNG,
        "            if not picked:\n                continue\n",
        "            if not picked:\n                return None\n",
        "문항 없는 묶음 건너뛰기(약한 순서)",
    ),
    # ── 축 C: 수능 장치가 재선택에서 빠진다 ────────────────────────────────────
    Mutation(
        "S12-suneung-priority-cancelled-on-reselection",
        SUNEUNG,
        _RESELECT_PICK,
        "            index = recommend_suneung_index(theta, picked, persona, extra_weights=["
        "(weights[i] if weights is not None else 1.0) / suneung_item_weight(p) "
        "for i, p in enumerate(picked)])\n",
        "재선택 수능 우선순위 가중",
    ),
    Mutation(
        "S13-extra-axes-skipped-on-reselection",
        SUNEUNG,
        "            weights, _weak_signal = await self._combine_axes(\n"
        "                user_id=user_id,\n",
        "            weights, _weak_signal = None, 0\n"
        "            _unused = dict(\n"
        "                user_id=user_id,\n",
        "재선택 약점·밴드·형제 가중",
    ),
    Mutation(
        "S14-attempted-not-passed-to-reselection",
        SUNEUNG,
        _TARGET_QUERY_ARGS,
        _TARGET_QUERY_ARGS.replace("attempted_ids=attempted_ids,", "attempted_ids=set(),"),
        "재선택 미응답 배제",
    ),
    Mutation(
        "S15-siblings-not-passed-to-reselection",
        SUNEUNG,
        _TARGET_QUERY_ARGS,
        _TARGET_QUERY_ARGS.replace("excluded_ids=excluded_ids,", "excluded_ids=set(),"),
        "재선택 형제 배제",
    ),
    Mutation(
        "S16-reselected-scores-not-its-comparison-set",
        SUNEUNG,
        "                scores=_suneung_candidate_scores(theta, picked, persona, weights),\n",
        "                scores=[],\n",
        "소급 평가 비교 집합",
    ),
    Mutation(
        "S17-graph-budget-not-passed",
        SUNEUNG,
        "            budget=self._graph_budget,\n",
        "",
        "그래프 예산 전달",
    ),
    # ── 축 D: 1차 선택 관측 불변 · 규칙 식별자 ─────────────────────────────────
    Mutation(
        "S18-weak-signal-counted-after-band",
        SUNEUNG,
        "        return extra_weights, weak_signal\n",
        "        return extra_weights, (sum(1 for w in extra_weights if w != 1.0) "
        "if extra_weights is not None else 0)\n",
        "약점 신호 정의(1차 관측 불변)",
    ),
    Mutation(
        "S19-policy-version-not-bumped",
        EVIDENCE,
        'POLICY_VERSION_SUNEUNG: str = "suneung_v2"',
        'POLICY_VERSION_SUNEUNG: str = "suneung_v1"',
        "정책 버전(REC-11)",
    ),
    # ── 서빙 경로(실 PG) — SQL과 정책 전체 ──────────────────────────────────────
    Mutation(
        "I01-primary-filter-dropped",
        SUNEUNG,
        _TARGET_WHERE,
        "            *suneung_pool_conditions(persona),\n",
        "대표 개념 한정",
        True,
    ),
    Mutation(
        "I02-prefilter-dropped-in-target-query",
        SUNEUNG,
        _TARGET_WHERE,
        "            ProblemConcept.role == ConceptRole.PRIMARY,\n",
        "재선택 사전필터",
        True,
    ),
    Mutation(
        "I03-persona-hardcoded-in-target-query",
        SUNEUNG,
        _TARGET_WHERE,
        _TARGET_WHERE.replace("(persona)", "(Persona.A_일반고고3)"),
        "사전필터 페르소나",
        True,
    ),
    Mutation(
        "I04-cap-is-global-not-per-concept",
        SUNEUNG,
        ".over(partition_by=ProblemConcept.concept_id, order_by=list(distance))",
        ".over(order_by=list(distance))",
        "개념별 상한",
        True,
    ),
    Mutation(
        "I05-attempted-not-excluded-in-sql",
        SUNEUNG,
        "    if attempted_ids:\n"
        "        inner = inner.where(Problem.problem_id.notin_(attempted_ids))\n",
        "    if False:\n        inner = inner.where(Problem.problem_id.notin_(attempted_ids))\n",
        "SQL 미응답 배제",
        True,
    ),
    Mutation(
        "I06-siblings-not-excluded-in-sql",
        SUNEUNG,
        "    if excluded_ids:\n"
        "        inner = inner.where(Problem.problem_id.notin_(excluded_ids))\n",
        "    if False:\n        inner = inner.where(Problem.problem_id.notin_(excluded_ids))\n",
        "SQL 형제 배제",
        True,
    ),
    Mutation(
        "I07-truth-gate-bypassed-on-live-path",
        SUNEUNG,
        _RESELECT_PICK,
        _UNGATED_PICK,
        "재선택 진실 게이트(실 PG)",
        True,
    ),
    Mutation(
        "I08-reselection-skipped-on-live-path",
        SUNEUNG,
        _RESELECT_BRANCH,
        _RESELECT_BRANCH.replace("if intent.reselect_groups:", "if False:"),
        "정렬 재선택(실 PG)",
        True,
    ),
]


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다."""
    for target in (SUNEUNG, EVIDENCE):
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
