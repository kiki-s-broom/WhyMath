#!/usr/bin/env python3
"""EOS-19 추천 정책 가드의 **결함 주입 검증** — 막으려는 상태를 실제로 주입해 RED를 본다.

CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"의 이행이다. 정상 입력에서
초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 가드도 같은 화면을 낸다.

이 하네스가 지키는 것(과거 사고에서 온 규율):

- **주입 자체의 실재**(2026-09-06): 치환이 실제로 적용됐는지(`mutated != original`)와 앵커가
  1건인지를 *테스트 실행 전에* 단언한다. 주입이 조용히 실패하면 정상 파일에 대해 테스트가
  돌고 "N passed"가 **검출 실패가 아니라 검출처럼** 보인다.
- **셸 배제**(2026-09-08): 치환은 순수 Python이다. heredoc·이스케이프를 거치지 않는다.
- **원복은 백업 복사**(2026-08-10): `git checkout --`을 쓰지 않는다 — 그것은 뮤테이션과
  미커밋 구현분을 구분하지 못하고 둘 다 되돌린다. 원복 후 바이트 동일성을 단언한다.
- **성공 방향 대조군**(2026-09-08): 무주입 실행이 GREEN인지 먼저 확인한다. 대조군이 없으면
  "전부 실패로 계상"이라는 과잉 수정도 통과한다.
- **판정은 exit code**(2026-08-09): 화면 문자열이 아니라 pytest의 종료 코드로 판정한다.

사용: `python3 scripts/analysis/mutate_recommendation_policy_guards.py`
종료 코드 0 = 전건 검출(가드가 실제로 막는다) · 1 = 생존한 뮤테이션 있음(가드가 위장이다).
"""

from __future__ import annotations

import argparse
import atexit
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

CONTRACT = BACKEND / "whymath_backend" / "l2" / "recommendation_contract.py"
POLICY = BACKEND / "whymath_backend" / "l2" / "recommendation_policy.py"
API_ME = BACKEND / "whymath_backend" / "api" / "me.py"

#: 빠른 판정용 테스트 표면. `api/me.py` 축은 응답 스키마 테스트 하나만 골라 돌린다
#: (전체 `test_me.py`는 35초라 11회 반복이 비싸다 — 변별력은 그 한 건이 이미 갖는다).
FAST_TESTS = [
    "../../tests/backend/l2/test_recommendation_policy.py",
    "../../tests/backend/l2/test_recommendation_contract.py",
]
API_TEST = "../../tests/backend/api/test_me.py"
API_TEST_FILTER = (
    "test_response_reason_field_is_required_not_optional "
    "or test_recommends_signature_item_same_response_schema or test_no_candidates_null "
    "or test_learning_purpose_alone_still_records_applied_weights"
)


@dataclass(frozen=True)
class Mutation:
    """뮤테이션 1건 — 어느 파일의 어느 절을 무엇으로 바꾸는가 + 무엇이 RED여야 하는가."""

    name: str
    path: Path
    old: str
    new: str
    axis: str  # 이 뮤테이션이 검사하는 축(보고용)
    api_surface: bool = False  # True면 `test_me.py` 필터를 함께 돌린다


MUTATIONS: list[Mutation] = [
    # ── 축 A: reason 제거 주입 (P-08 완료 판정의 대상) ───────────────────────────
    Mutation(
        name="M1-reason-optional-on-contract",
        path=CONTRACT,
        old="\n    reason: RecommendationReason\n",
        new="\n    reason: RecommendationReason | None = None\n",
        axis="근거 필수",
    ),
    Mutation(
        name="M2-reason-optional-on-response",
        path=API_ME,
        old="    reason: RecommendationReason = Field(\n        description=(",
        new=(
            "    reason: RecommendationReason | None = Field(\n"
            "        default=None,\n        description=("
        ),
        axis="근거 필수(응답 경계)",
        api_surface=True,
    ),
    Mutation(
        name="M3-action-derivation-removed",
        path=CONTRACT,
        old='        if not isinstance(data, dict) or "action" in data:\n',
        new="        if True:\n            return data\n        if False:\n",
        axis="행위 파생",
    ),
    Mutation(
        name="M4-action-consistency-check-removed",
        path=CONTRACT,
        old="        if self.action is not expected:",
        new="        if False:",
        axis="행위↔근거 정합",
    ),
    # ── 축 B: depth·nodes 예산을 푸는 주입 (P-08 검증 ②) ────────────────────────
    Mutation(
        name="M5-depth-ceiling-raised",
        path=POLICY,
        old="_DEPTH_CEILING = 2",
        new="_DEPTH_CEILING = 5",
        axis="깊이 천장",
    ),
    Mutation(
        name="M6-nodes-ceiling-raised",
        path=POLICY,
        old="_NODES_CEILING = 20",
        new="_NODES_CEILING = 100",
        axis="너비 천장",
    ),
    Mutation(
        name="M7-depth-validation-removed",
        path=POLICY,
        old="        if not 1 <= self.max_depth <= _DEPTH_CEILING:",
        new="        if False:",
        axis="깊이 검증",
    ),
    Mutation(
        name="M8-nodes-validation-removed",
        path=POLICY,
        old="        if not 1 <= self.max_nodes <= _NODES_CEILING:",
        new="        if False:",
        axis="너비 검증",
    ),
    Mutation(
        name="M9-traversal-ignores-budget",
        path=POLICY,
        old="max_depth=budget.max_depth)",
        new="max_depth=5)",
        axis="예산 전달(미사용 예산 탐지)",
    ),
    Mutation(
        name="M10-visited-set-removed",
        path=POLICY,
        old="        if row.concept_id in visited:\n            continue",
        new="        if False:\n            continue",
        axis="visited set",
    ),
    Mutation(
        name="M11-node-budget-not-applied",
        path=POLICY,
        old="    if len(deduped) <= budget.max_nodes:\n        return deduped",
        new="    if True:\n        return deduped",
        axis="너비 예산 적용",
    ),
    # ── 축 C: 회귀 재발 주입 — 전환 중 실제로 났던 오류를 되살린다 ────────────────
    Mutation(
        name="M13-applied-weights-derived-from-honest-axes",
        path=API_ME,
        old="            applied_weights=outcome.applied_weights,",
        new="            applied_weights=bool(outcome.weight_axes_applied),",
        axis="처치 기록 가중 플래그(회귀 재발)",
        api_surface=True,
    ),
    Mutation(
        name="M12-timeout-removed",
        path=POLICY,
        old="asyncio.timeout(budget.timeout_seconds)",
        new="asyncio.timeout(3600)",
        axis="시간 예산",
    ),
]


def run_pytest(mutation: Mutation | None) -> int:
    """대상 테스트를 돌리고 **종료 코드**를 돌려준다(화면 문자열로 판정하지 않는다)."""
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
        *FAST_TESTS,
    ]
    if mutation is not None and mutation.api_surface:
        args = args[: -len(FAST_TESTS)] + [API_TEST, "-k", API_TEST_FILTER]
    # 뮤테이션이 들어간 실행도 **빨리** 끝나야 한다 — 매달리는 뮤테이션은 검증을 중단시키고,
    # 중단은 원복을 건너뛴다. 대역(`_SpyFetch.HANG_SECONDS`)이 초 단위로 맞춰져 있다.
    # HARN-19: 서브프로세스 출력 디코딩은 **인코딩을 명시**한다 — 로케일 기본(한국어
    # Windows=cp949)으로 디코드하면 UTF-8 출력이 붕괴한다. `tests/harness/
    # test_subprocess_encoding.py`가 이 규칙을 동결하며, 실제로 이 파일의 첫 판본을 잡았다.
    proc = subprocess.run(
        args,
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="이름에 이 문자열이 든 뮤테이션만 실행")
    args = parser.parse_args()

    selected = [m for m in MUTATIONS if not args.only or args.only in m.name]

    # ── 성공 방향 대조군 — 무주입이 GREEN이어야 이후 RED가 의미를 가진다 ──
    baseline = run_pytest(None)
    print(f"[대조군] 무주입 스위트 exit={baseline} ({'GREEN' if baseline == 0 else 'RED'})")
    if baseline != 0:
        print("✗ 대조군이 이미 RED다 — 이 상태에서는 어떤 뮤테이션도 '검출'로 계상할 수 없다")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        backups = {}
        for path in {m.path for m in selected}:
            backup = Path(tmp) / path.name
            shutil.copy2(path, backup)  # git이 아니라 파일 복사로 원복한다(2026-08-10 규율)
            backups[path] = backup

        def restore_all() -> None:
            """어떤 종료 경로에서도 원복한다 — **중단은 원복을 건너뛴다**(2026-09-18 실측).

            `finally`는 정상 흐름과 예외만 덮는다. 사람이·하네스가 프로세스를 죽이면 그 블록은
            돌지 않고 **뮤테이션이 작업 트리에 남는다**. 남은 뮤테이션은 무증상이라(파일은
            문법적으로 멀쩡하다) 다음 검증이 그것을 원본으로 착각한다.
            """
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
                code = run_pytest(m)
                detected = code != 0
                mark = "RED(검출)" if detected else "GREEN(생존)"
                print(f"  {m.name:<38} axis={m.axis:<22} exit={code} {mark}")
                if not detected:
                    survivors.append(m.name)
            finally:
                shutil.copy2(backups[m.path], m.path)
                restored = m.path.read_bytes()
                original = backups[m.path].read_bytes()
                if restored != original:
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
