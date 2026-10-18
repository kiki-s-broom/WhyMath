#!/usr/bin/env python3
"""EOS-26 R6 집행 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

대상은 원인 미상 오답(R6) 집행 경로다: `l2/learning_state_recommendation.py`의 판정 트리(지시
판독 · 연속 둘째 · 막힘 문턱 · 아는 결손 · 미측정 선수 탐침 · 같은 개념 폴백)와
`l2/recommendation_policy.py`의 정책 이음매(후보 제한 · 연습 경로 학습 밴드 · 정책 버전 · 전진
보류 · 예산을 건 선수 읽기). 설계 정본은
`docs/reviews/eos26_r6_diagnosis_prerequisite_directed_judgment_2026-09-26.md`(§9가 이 하네스의
실행 결과를 인용한다).

규율은 선례 `scripts/analysis/mutate_recommendation_policy_guards.py`와 같다 — 주입 실재 단언
(앵커 1건 · 치환 후 원본과 다름) · 순수 Python 치환 · 백업 복사 원복(git 원복 금지)과 바이트
동일성 단언 · 중단(시그널)에도 원복 · 성공 방향 대조군 · 판정은 pytest 종료 코드. 여기에 더해
실행마다 대상 모듈의 바이트코드 캐시를 지운다(`drop_bytecode` — 캐시가 앞 뮤테이션 코드를 실행하는
함정 · `HARN-120` ⑤).

표면이 둘이다:

- **단위**(기본): `tests/backend/l2/test_learning_state_recommendation.py` — DB 없이 판정 트리와
  정책 이음매를 잰다.
- **서빙 경로**(`--with-integration`): 실 PostgreSQL · HTTP 경로 통합 테스트 3파일. 환경변수
  `WHYMATH_DATABASE_URL`(asyncpg URL · 마이그레이션 적용된 DB)이 필요하다. 이 표면은 "단위에서
  잡힌다"가 아니라 "학생 응답(`GET /v1/me/next-problem`)이 실제로 바뀐다"를 확인한다.

사용: `python3 scripts/analysis/mutate_eos26_r6_guards.py [--with-integration] [--only 이름조각]`
종료 코드 0 = 전건 검출 · 1 = 생존한 뮤테이션 있음(가드가 위장이다) 또는 대조군 RED.
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

LSR = BACKEND / "whymath_backend" / "l2" / "learning_state_recommendation.py"
POLICY = BACKEND / "whymath_backend" / "l2" / "recommendation_policy.py"

UNIT_TESTS = ["../../tests/backend/l2/test_learning_state_recommendation.py"]
INTEGRATION_TESTS = [
    "../../tests/backend/api/test_eos26_r6_prerequisite_probe.py",
    "../../tests/backend/api/test_eos24_recommendation_follows_learning_state.py",
    "../../tests/backend/api/test_e2e_three_consecutive_loops.py",
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


_DIRECTIVE_TRIGGER = (
    "    if snapshot.trigger is not TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED:\n"
    "        return None\n"
    "    return UndiagnosedWrongDirective"
)
_DIRECTIVE_STATE = (
    "    if snapshot is None or snapshot.state is not LearningState.PRACTICING:\n"
    "        return None\n"
    "    if snapshot.trigger is not TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED:"
)
_REPEAT = "    if previous in _WRONG_ANSWER_DECISIONS:"
_BLOCKED = "    if anchor_mastery >= PREREQUISITE_MASTERY_CEILING:"
_DEFICIT = "    if any(status is _PrerequisiteStatus.WEAK for _row, status in statuses):"
_UNMEASURED_POOL = (
    "    unmeasured = [\n"
    "        row.concept_id for row, status in statuses"
    " if status is _PrerequisiteStatus.UNMEASURED\n"
    "    ]"
)
_R6_WIRING = (
    "        if undiagnosed is None:\n"
    "            return None\n"
    "        return await _route_undiagnosed_wrong("
)
_R6_WIRING_CUT = (
    "        if undiagnosed is None or undiagnosed is not None:\n"
    "            return None\n"
    "        return await _route_undiagnosed_wrong("
)
_RESTRICTED = (
    "        restricted_route = applied_route if applied_route is not None else undiagnosed_route"
)
_PRACTICE_BAND = (
    "            or (undiagnosed_route is not None and undiagnosed_route.undiagnosed_practice)\n"
)
_UNMEASURED_WARN = (
    "        _logger.warning(\n"
    '            "R6 선수 탐침 — 오답 직후인데 오답 개념의 숙달 측정이 없다(숙달 전파 공백)'
    ' · 같은 개념 "\n'
    '            "연습으로 집행. concept=%s attempt=%s",\n'
    "            concept_id,\n"
    "            directive.attempt_id,\n"
    "        )\n"
)
_ADVANCE_GUARD = (
    "            if undiagnosed_route is not None"
    " and anchor_reason.type is ReasonType.NEXT_CONCEPT:"
)

MUTATIONS: list[Mutation] = [
    # ── 지시 판독(판정문 §3 ⓓ) — 국면과 트리거를 둘 다 본다 ─────────────────────
    Mutation(
        "M01-directive-trigger-check-removed",
        LSR,
        _DIRECTIVE_TRIGGER,
        "    return UndiagnosedWrongDirective",
        "R2 비집행(트리거)",
    ),
    Mutation(
        "M02-directive-state-check-removed",
        LSR,
        _DIRECTIVE_STATE,
        "    if snapshot is None:\n"
        "        return None\n"
        "    if snapshot.trigger is not TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED:",
        "지시 판독(국면)",
    ),
    # ── 연속 둘째(ⓒ) — 직전 정책 결정이 R3·R6면 탐침하지 않는다 ───────────────────
    Mutation("M03-repeat-any-previous", LSR, _REPEAT, "    if previous is not None:", "연속 판정"),
    Mutation("M04-repeat-branch-dead", LSR, _REPEAT, "    if False:", "연속 판정"),
    Mutation(
        "M05-repeat-only-after-r6",
        LSR,
        "        TransitionTrigger.POLICY_REMEDIATE_MISCONCEPTION,\n"
        "        TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,\n"
        "    }",
        "        TransitionTrigger.POLICY_PRACTICE_UNDIAGNOSED,\n    }",
        "연속 판정(R3 포함 — 발견 4B)",
    ),
    Mutation(
        "M06-previous-includes-this-attempt",
        LSR,
        "            LearningStateTransition.attempt_id != attempt_id,\n"
        "            LearningStateTransition.trigger.in_(POLICY_DECISION_TRIGGERS),",
        "            LearningStateTransition.trigger.in_(POLICY_DECISION_TRIGGERS),",
        "직전 결정 조회(결정 응답 제외)",
    ),
    Mutation(
        "M07-previous-any-trigger",
        LSR,
        "            LearningStateTransition.trigger.in_(POLICY_DECISION_TRIGGERS),\n",
        "",
        "직전 결정 조회(정책 결정만)",
    ),
    Mutation(
        "M08-previous-oldest-first",
        LSR,
        "            desc(LearningStateTransition.occurred_at),\n"
        "            desc(LearningStateTransition.transition_id),\n"
        "        )\n"
        "        .limit(1)",
        "            LearningStateTransition.occurred_at,\n"
        "            LearningStateTransition.transition_id,\n"
        "        )\n"
        "        .limit(1)",
        "직전 결정 조회(최신순)",
    ),
    # ── 막힘 문턱(발견 2) — 오답 개념이 선수 구간일 때만 선수 쪽으로 ───────────────
    Mutation(
        "M09-blocked-boundary-gt",
        LSR,
        _BLOCKED,
        "    if anchor_mastery > PREREQUISITE_MASTERY_CEILING:",
        "막힘 경계(0.40)",
    ),
    Mutation("M10-blocked-gate-removed", LSR, _BLOCKED, "    if False:", "막힘 문턱"),
    Mutation(
        "M11-blocked-gate-wrong-ceiling",
        LSR,
        _BLOCKED,
        # 리터럴 — EOS-151 뒤 이 모듈은 WEAK_CONCEPT_MASTERY_CEILING을 import하지 않는다. 이름으로
        # 두면 NameError로 RED가 나 의미 뮤테이션(막힘 문턱을 0.7로 올림)이 아니게 된다.
        "    if anchor_mastery >= 0.7:",
        "막힘 문턱(선수 경계 0.4)",
    ),
    Mutation(
        "M12-unmeasured-anchor-as-blocked",
        LSR,
        "    anchor_mastery = float(row.mastery)"
        " if row is not None and row.mastery is not None else None",
        "    anchor_mastery = float(row.mastery)"
        " if row is not None and row.mastery is not None else 0.0",
        "모른다≠막혔다(오답 개념 미측정)",
    ),
    Mutation("M13-unmeasured-anchor-silent", LSR, _UNMEASURED_WARN, "", "침묵 실패 금지"),
    Mutation(
        "M14-mastery-read-other-concept",
        LSR,
        "    row = await _latest_mastery(session, user_id, concept_id)",
        "    row = await _latest_mastery(session, user_id, uuid.uuid4())",
        "숙달 조회 대상",
    ),
    # ── 선수 읽기 · 시간 예산(ⓕ) ─────────────────────────────────────────────────
    Mutation(
        "M15-probe-depth-2",
        LSR,
        "_PROBE_DEPTH: Final = 1",
        "_PROBE_DEPTH: Final = 2",
        "직접 선수만(ⓑ)",
    ),
    Mutation(
        "M16-timeout-not-caught",
        LSR,
        "    except TimeoutError as exc:",
        "    except ZeroDivisionError as exc:",
        "시간 예산 강등",
    ),
    Mutation(
        "M17-timeout-log-untyped",
        LSR,
        "            type(exc).__name__,\n"
        "            concept_id,\n"
        "        )\n"
        "        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT)",
        '            "?",\n'
        "            concept_id,\n"
        "        )\n"
        "        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_GRAPH_TIMEOUT)",
        "예외 타입명 로그",
    ),
    Mutation(
        "M18-unsupported-to-default-path",
        LSR,
        "        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED)",
        "        return StateRoute(outcome=StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNSUPPORTED)",
        "폴백 = 같은 개념(ⓐ)",
    ),
    # ── 아는 결손(발견 8) — 측정된 약점이 있으면 탐침하지 않는다 ─────────────────
    Mutation("M19-known-deficit-removed", LSR, _DEFICIT, "    if False:", "아는 결손"),
    Mutation(
        "M20-known-deficit-needs-all",
        LSR,
        _DEFICIT,
        "    if all(status is _PrerequisiteStatus.WEAK for _row, status in statuses):",
        "아는 결손 우선",
    ),
    # EOS-151 재앵커 — 분류기가 (가)의 결손 술어를 부른다. 경계 자체(`<` vs `<=` · 0.3)의
    # 뮤테이션은 술어의 소유자인 EOS-33 하네스(`mutate_eos33_evidence_floor_guards.py`)가 맡고,
    # 여기서는 분류기가 술어를 **우회**해 자기 경계를 갖는 형태를 주입한다(리터럴 — 이름을 쓰면
    # import 부재로 RED가 난다).
    Mutation(
        "M21-weak-classifier-own-boundary-0.7",
        LSR,
        "    if is_prerequisite_deficit(mastery):\n        return _PrerequisiteStatus.WEAK",
        "    if mastery < 0.7:\n        return _PrerequisiteStatus.WEAK",
        "결손 술어 공유(0.7 복귀 = EOS-151 정합 이전 · 0.3~0.7을 아는 결손으로)",
    ),
    Mutation(
        "M21b-weak-classifier-own-boundary-le",
        LSR,
        "    if is_prerequisite_deficit(mastery):\n        return _PrerequisiteStatus.WEAK",
        "    if mastery <= 0.3:\n        return _PrerequisiteStatus.WEAK",
        "결손 술어 공유(자체 경계 `<=` 0.3 — 사전값 자체를 결손으로)",
    ),
    Mutation(
        "M22-unmeasured-status-as-strong",
        LSR,
        "    if mastery is None:\n        return _PrerequisiteStatus.UNMEASURED",
        "    if mastery is None:\n        return _PrerequisiteStatus.STRONG",
        "모른다≠숙달",
    ),
    # ── 탐침 풀 — 미측정 선수만 · 기본 풀과 같은 정렬 ──────────────────────────────
    Mutation(
        "M23-probe-pool-all-prerequisites",
        LSR,
        _UNMEASURED_POOL,
        "    unmeasured = [row.concept_id for row, status in statuses]",
        "탐침 = 미측정만(발견 3)",
    ),
    Mutation(
        "M24-refuted-branch-removed",
        LSR,
        "    if not unmeasured:\n"
        "        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_REFUTED)\n",
        "",
        "반증 폴백",
    ),
    Mutation(
        "M25-unavailable-to-default-path",
        LSR,
        "        return await same_concept(StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE)",
        "        return StateRoute(outcome=StateDirectiveOutcome.SAME_CONCEPT_PROBE_UNAVAILABLE)",
        "폴백 = 같은 개념(ⓐ)",
    ),
    Mutation(
        "M26-probe-no-dedup",
        LSR,
        "        if pid in seen:\n            continue\n"
        "        seen.add(pid)\n        merged.append",
        "        merged.append",
        "탐침 풀 중복 제거",
    ),
    Mutation(
        "M27-probe-no-sort",
        LSR,
        "    merged.sort(key=lambda row: (abs(_item_b(row) - theta), str(row[0])))\n",
        "",
        "탐침 풀 정렬",
    ),
    Mutation(
        "M28-probe-no-tiebreak",
        LSR,
        "(abs(_item_b(row) - theta), str(row[0]))",
        "(abs(_item_b(row) - theta),)",
        "탐침 풀 동률 키",
    ),
    Mutation(
        "M29-probe-no-cap",
        LSR,
        "    return tuple(merged[:CANDIDATE_POOL_SIZE])",
        "    return tuple(merged)",
        "탐침 풀 상한",
    ),
    # ── 경로 집합 · 배선 ─────────────────────────────────────────────────────────
    Mutation(
        "M30-probe-missing-from-restricting",
        LSR,
        "        StateDirectiveOutcome.PREREQUISITE_PROBE,\n"
        "        StateDirectiveOutcome.SAME_CONCEPT_REPEAT,",
        "        StateDirectiveOutcome.SAME_CONCEPT_REPEAT,",
        "집행 집합",
    ),
    Mutation(
        "M31-deficit-missing-from-restricting",
        LSR,
        "        StateDirectiveOutcome.KNOWN_PREREQUISITE_DEFICIT,\n",
        "",
        "집행 집합",
    ),
    Mutation(
        "M32-practice-set-includes-probe",
        LSR,
        "_UNDIAGNOSED_RESTRICTING - {\n    StateDirectiveOutcome.PREREQUISITE_PROBE\n}",
        "_UNDIAGNOSED_RESTRICTING",
        "연습 집합(탐침 제외)",
    ),
    Mutation("M33-r6-branch-unwired", LSR, _R6_WIRING, _R6_WIRING_CUT, "R6 배선"),
    # ── 정책 이음매 ──────────────────────────────────────────────────────────────
    Mutation(
        "M34-policy-ignores-r6-pool",
        POLICY,
        _RESTRICTED,
        "        restricted_route = applied_route",
        "후보 제한 집행",
    ),
    Mutation(
        "M35-policy-version-not-split",
        POLICY,
        "            policy_version = POLICY_VERSION_CAT_STATE_UNDIAGNOSED",
        "            policy_version = self.policy_version",
        "정책 버전 분리(ⓖ)",
    ),
    Mutation(
        "M36-advance-guard-removed", POLICY, _ADVANCE_GUARD, "            if False:", "전진 보류"
    ),
    Mutation(
        "M37-advance-guard-leaks",
        POLICY,
        _ADVANCE_GUARD,
        "            if anchor_reason.type is ReasonType.NEXT_CONCEPT:",
        "전진 보류(R6 경로 한정)",
    ),
    Mutation(
        "M38-guard-resolution-refuted",
        POLICY,
        "                intent = _demoted(anchor_reason, IntentResolution.STATE_WITHHELD)",
        "                intent = _demoted(anchor_reason, IntentResolution.REFUTED)",
        "해소값 state_withheld(발견 12)",
    ),
    Mutation(
        "M39-practice-band-not-applied",
        POLICY,
        _PRACTICE_BAND,
        "",
        "연습 학습 밴드(발견 6)",
    ),
    Mutation(
        "M40-practice-band-on-probe-too",
        POLICY,
        "undiagnosed_route.undiagnosed_practice)",
        "undiagnosed_route.undiagnosed_applied)",
        "탐침은 요청 목적",
    ),
    Mutation(
        "M41-reselection-original-context",
        POLICY,
        "                    learning_context=effective_context,\n                    theta=theta,",
        "                    learning_context=learning_context,\n                    theta=theta,",
        "재선택 요청 상황",
    ),
    Mutation(
        "M42-first-selection-original-context",
        POLICY,
        "            learning_context=effective_context,\n"
        "            candidate_rows=candidate_rows,",
        "            learning_context=learning_context,\n"
        "            candidate_rows=candidate_rows,",
        "1차 선택 요청 상황",
    ),
    Mutation(
        "M43-reader-depth-unclamped",
        POLICY,
        "        depth = min(max_depth, self._graph_budget.max_depth)",
        "        depth = max_depth",
        "깊이 천장(ⓕ)",
    ),
    Mutation(
        "M44-reader-node-budget-off",
        POLICY,
        "        return _apply_node_budget(rows, self._graph_budget)\n\n"
        "    async def _select_aligned(",
        "        return list(rows)\n\n    async def _select_aligned(",
        "너비 예산(ⓕ)",
    ),
    Mutation(
        "M45-policy-injects-other-reader",
        POLICY,
        "            read_prerequisites=self._read_prerequisites,",
        "            read_prerequisites=lambda c, d: self._read_prerequisites(c, 2),",
        "예산 소유(정책 읽기 주입)",
    ),
    # ── 서빙 경로(실 PG · HTTP) — 학생 응답이 실제로 바뀌는가 ─────────────────────
    Mutation("I01-r6-branch-unwired", LSR, _R6_WIRING, _R6_WIRING_CUT, "R6 배선", True),
    Mutation("I02-repeat-branch-dead", LSR, _REPEAT, "    if False:", "연속 판정(ⓑ)", True),
    Mutation("I03-blocked-gate-removed", LSR, _BLOCKED, "    if False:", "막힘 문턱", True),
    Mutation("I04-known-deficit-removed", LSR, _DEFICIT, "    if False:", "아는 결손", True),
    Mutation(
        "I05-probe-pool-all-prerequisites",
        LSR,
        _UNMEASURED_POOL,
        "    unmeasured = [row.concept_id for row, status in statuses]",
        "탐침 = 미측정만",
        True,
    ),
    Mutation(
        "I06-r2-read-as-directive",
        LSR,
        _DIRECTIVE_TRIGGER,
        "    return UndiagnosedWrongDirective",
        "R2 비집행",
        True,
    ),
    Mutation(
        "I07-policy-ignores-r6-pool",
        POLICY,
        _RESTRICTED,
        "        restricted_route = applied_route",
        "후보 제한 집행",
        True,
    ),
    Mutation(
        "I08-probe-depth-2",
        LSR,
        "_PROBE_DEPTH: Final = 1",
        "_PROBE_DEPTH: Final = 2",
        "직접 선수만",
        True,
    ),
    Mutation("I09-practice-band-not-applied", POLICY, _PRACTICE_BAND, "", "연습 학습 밴드", True),
    Mutation(
        "I10-practice-band-on-probe-too",
        POLICY,
        "undiagnosed_route.undiagnosed_practice)",
        "undiagnosed_route.undiagnosed_applied)",
        "탐침은 요청 목적",
        True,
    ),
]


def drop_bytecode() -> None:
    """대상 모듈의 바이트코드 캐시를 지운다 — 디스크의 뮤테이션과 실행되는 코드를 일치시킨다.

    `.pyc` 무효화 검사는 '초 단위 수정 시각 + 소스 크기'라, 크기 변화가 같은 두 뮤테이션이 같은 1초
    안에 쓰이면 앞 뮤테이션의 캐시가 뒤 실행에 재사용된다(디스크엔 뒤 뮤테이션, 실행된 코드는 앞
    뮤테이션 — 거짓 생존도 거짓 검출도 가능). 2026-09-26 HARN-176 실측 · 처방은 `HARN-120` ⑤다.
    실행마다 여기서 지우고 `PYTHONDONTWRITEBYTECODE=1`로 돌려 새 캐시도 남기지 않는다.
    """
    for target in (LSR, POLICY):
        for cached in (target.parent / "__pycache__").glob(f"{target.stem}.*.pyc"):
            cached.unlink()


def run_pytest(*, integration: bool) -> int:
    """대상 표면을 돌리고 **종료 코드**를 돌려준다(화면 문자열로 판정하지 않는다)."""
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
        "-x",
        *targets,
    ]
    # HARN-19: 서브프로세스 출력 디코딩은 인코딩을 명시한다(`tests/harness/test_subprocess_
    # encoding.py`가 동결). 매달리는 뮤테이션은 원복을 건너뛰게 하므로 시간 상한을 건다.
    proc = subprocess.run(
        args,
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1500,
    )
    return proc.returncode


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
        print(f"[대조군:{label}] 무주입 exit={baseline} ({'GREEN' if baseline == 0 else 'RED'})")
        if baseline != 0:
            print("✗ 대조군이 이미 RED다 — 이 상태에서는 어떤 뮤테이션도 '검출'로 계상할 수 없다")
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
                detected = code != 0
                mark = "RED(검출)" if detected else "GREEN(생존)"
                surface = "서빙" if m.integration else "단위"
                print(f"  {m.name:<40} [{surface}] axis={m.axis:<24} exit={code} {mark}")
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
