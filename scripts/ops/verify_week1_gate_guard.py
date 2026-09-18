"""Week 1 Gate 가드의 **변별력 검증** — 막으려는 상태를 실제로 주입해 RED를 확인한다.

대상: `tests/backend/api/test_week1_gate_no_learner_writes.py`(판정 하네스가 학습자 상태를 DB에
직접 쓰지 않는다는 규율을 AST로 집행하는 가드).

정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 가드도 같은 화면을
낸다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"). 그래서 이 스크립트는
가드가 막겠다고 선언한 상태를 9종으로 나눠 주입하고, 각 주입이 **그 검사에서** RED를 내는지 본다.

셸을 배제한 순수 Python 하네스다 — 셸 이스케이프로 주입이 조용히 실패하면 "통과"가 "검출"처럼
보인다(2026-09-06 사고 유형). 그래서 주입마다 ①치환 대상이 1건 이상인지 ②`mutated != original`
인지 ③원복이 **바이트 동일**한지를 각각 단언하고, 종료 시 sha256을 대조한다. 원복은 `cp`로 뜬
백업을 `cp`로 되돌린다(`git checkout --`는 미커밋 구현분까지 함께 되돌려 무증상으로 날린다 —
CLAUDE.md 2026-08-10 등재 금기).

판정: **exit 0 = 9종 전건 RED + 대조군 GREEN + 바이트 동일 원복**. 그 밖은 exit 1(생존·주입
실패·원복 불일치), exit 2(정상 상태에서 이미 RED — 가드나 하네스 자체가 잘못됐다).

**CI 미배선 — 의도된 것**: 이 스크립트는 추적 중인 파일을 제자리에서 고쳐 쓴다. CI 잡에 얹으면
중단·타임아웃 시 뮤테이션된 트리가 남아 *다른* 검사를 거짓 red/green으로 만든다(CLAUDE.md
"검증이 도는 동안 작업 트리를 바꾸지 않는다"의 역방향 위험). 가드 자체는 backend 잡의 pytest가
상시 실행하고, 이 스크립트는 가드를 **고칠 때** 사람이 돌리는 일회성 검증 도구다.

    python3 scripts/ops/verify_week1_gate_guard.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import types

REPO = pathlib.Path("/home/user/WhyMath")
HARNESS = REPO / "tests/backend/api/test_week1_gate_closed_loop.py"
GUARD = REPO / "tests/backend/api/test_week1_gate_no_learner_writes.py"


def _install_pytest_stub() -> None:
    """실제 가드 코드를 그대로 임포트하기 위한 최소 pytest 스텁(fixture 데코레이터만 쓴다)."""
    if "pytest" in sys.modules:
        return
    stub = types.ModuleType("pytest")

    def fixture(*args, **kwargs):  # type: ignore[no-untyped-def]
        if args and callable(args[0]):
            return args[0]

        def deco(fn):  # type: ignore[no-untyped-def]
            return fn

        return deco

    stub.fixture = fixture  # type: ignore[attr-defined]

    def skip(reason: str = "") -> None:
        raise RuntimeError(f"skip: {reason}")

    stub.skip = skip  # type: ignore[attr-defined]
    sys.modules["pytest"] = stub


def _load_guard() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("w1_guard", GUARD)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECKS = (
    "test_harness_constructs_no_learner_state_rows",
    "test_harness_raw_sql_is_teardown_only",
    "test_harness_still_judges_all_seven_steps",
)


def run_checks(guard: types.ModuleType) -> dict[str, str]:
    """세 검사를 돌려 각각 PASS/FAIL(AssertionError)을 돌려준다."""
    tree = guard.harness_tree()
    out: dict[str, str] = {}
    for name in CHECKS:
        try:
            getattr(guard, name)(tree)
            out[name] = "PASS"
        except AssertionError as exc:
            out[name] = f"FAIL({str(exc).splitlines()[0][:70]})"
    return out


# (라벨, 원본 조각, 치환 조각, 이 주입이 RED를 내야 하는 검사)
MUTATIONS = [
    (
        "M1 학습자 상태 생성 — ProblemAttempt 직접 insert",
        "            session.add_all(list(objs))",
        "            session.add_all(list(objs) + [ProblemAttempt()])",
        "test_harness_constructs_no_learner_state_rows",
    ),
    (
        "M2 학습자 상태 생성 — UserProfile.from_schema 직접 시딩",
        "def _concept(cid: uuid.UUID, code: str, name: str) -> Concept:",
        "def _seed_user() -> object:\n    return UserProfile.from_schema(None)\n\n\n"
        "def _concept(cid: uuid.UUID, code: str, name: str) -> Concept:",
        "test_harness_constructs_no_learner_state_rows",
    ),
    (
        "M3 학습자 상태 생성 — ConceptMasteryHistory 기준선 시딩",
        "            before_users = asyncio.run(_demo_user_ids())",
        "            asyncio.run(_add_all(ConceptMasteryHistory()))\n"
        "            before_users = asyncio.run(_demo_user_ids())",
        "test_harness_constructs_no_learner_state_rows",
    ),
    (
        "M4 원시 SQL 쓰기 — INSERT로 숙달 기준선 주입",
        'text("DELETE FROM problem_concept WHERE problem_id = ANY(:ids)")',
        'text("INSERT INTO concept_mastery_history VALUES (1)")',
        "test_harness_raw_sql_is_teardown_only",
    ),
    (
        "M5 원시 SQL 쓰기 — UPDATE로 mastery 값 조작",
        'text("DELETE FROM problem WHERE problem_id = ANY(:ids)")',
        'text("UPDATE concept_mastery_history SET mastery = 0.1")',
        "test_harness_raw_sql_is_teardown_only",
    ),
    (
        "M6 단계 삭제 — 6단계(mastery 변경) 라벨 제거",
        '                "6-mastery-changed",',
        '                "6-mastery-changed-DROPPED",',
        "test_harness_still_judges_all_seven_steps",
    ),
    (
        "M7 단계 삭제 — 1단계(사용자 생성) 라벨 제거",
        '            _step("1-user-created", f"user_profile 0건→1건 · uid={uid}',
        '            _step("1-user-created-DROPPED", f"user_profile 0건→1건 · uid={uid}',
        "test_harness_still_judges_all_seven_steps",
    ),
    (
        "M8 가드 스캔 무력화 — 콘텐츠 시딩 제거(스캔 0건=실패 축)",
        "    return Concept.from_schema(",
        "    return _make(",
        "test_harness_constructs_no_learner_state_rows",
    ),
    (
        "M9 가드 스캔 무력화 — text() 호출 전건 제거(스캔 0건=실패 축)",
        "text(",
        "renamed_sql(",
        "test_harness_raw_sql_is_teardown_only",
    ),
]


def main() -> int:
    _install_pytest_stub()
    original = HARNESS.read_bytes()
    orig_sha = hashlib.sha256(original).hexdigest()
    backup = pathlib.Path(tempfile.mkdtemp()) / HARNESS.name
    shutil.copy2(HARNESS, backup)

    guard = _load_guard()
    baseline = run_checks(guard)
    print("=== 대조군(정상 하네스) ===")
    for k, v in baseline.items():
        print(f"  {k}: {v}")
    if any(v != "PASS" for v in baseline.values()):
        print("!! 정상 상태에서 이미 RED — 가드나 하네스가 잘못됐다")
        return 2

    failures = 0
    print("\n=== 뮤테이션 주입 ===")
    for label, old, new, expect_check in MUTATIONS:
        text = original.decode("utf-8")
        count = text.count(old)
        if count < 1:
            print(f"  {label}: !! 주입 대상 0건 — 하네스 결함(치환 문자열 불일치)")
            failures += 1
            continue
        mutated = text.replace(old, new)
        assert mutated != text, f"{label}: 주입이 적용되지 않았다"
        HARNESS.write_text(mutated, encoding="utf-8")
        try:
            got = run_checks(guard)
        finally:
            shutil.copy2(backup, HARNESS)
            restored = HARNESS.read_bytes()
            assert restored == original, f"{label}: 원복이 바이트 동일하지 않다"
        verdict = got[expect_check]
        red = verdict.startswith("FAIL")
        others = {k: v for k, v in got.items() if k != expect_check}
        print(f"  {label}")
        print(f"    대상 {count}건 치환 · {expect_check} -> {verdict}")
        if not red:
            print(f"    !! 생존(가드가 못 잡았다). 다른 검사: {others}")
            failures += 1

    final_sha = hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    same = "동일" if orig_sha == final_sha else "불일치!!"
    print(f"\n원본 sha256={orig_sha[:16]} · 종료 후 sha256={final_sha[:16]} · {same}")
    print(f"뮤테이션 {len(MUTATIONS)}종 · 생존/결함 {failures}건")
    return 1 if failures or orig_sha != final_sha else 0


if __name__ == "__main__":
    sys.exit(main())
