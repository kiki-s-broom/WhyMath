#!/usr/bin/env python3
"""S1 실기기 시연 시드 — 진단 문제 코퍼스를 backend에 멱등 적재한다.

`/v1/me/next-problem`이 시연에서 문제 카드를 띄우려면 `difficulty_overall`이 채워진 *미시도*
문제가 최소 1건 적재돼 있어야 한다. 이 스크립트는 `l1.problem_bank.populate`를 재사용해(재구현
금지) `data/corpus/problem_bank_v1/problems.jsonl`을 `problem`/`problem_concept`에 적재한다.

**데모 사용자는 시드하지 않는다(의도)**: 콜백(`POST /v1/auth/demo/callback`)이 처음 호출될 때
`resolve_user`가 고정 데모 계정을 lazy upsert하므로, run 스크립트가 콜백으로 토큰을 발급하는 순간
사용자 행이 생긴다(실 로그인 경로를 더 많이 태워 시연 신뢰도↑). 따라서 여기선 문제만 적재한다.

전제: backend 패키지 설치·`WHYMATH_DATABASE_URL` 도달 가능·`alembic upgrade head` 선행
(run 스크립트 담당). CWD 무관하게 동작하도록 코퍼스 경로를 리포 루트 기준으로 해석한다.
"""

from __future__ import annotations

from pathlib import Path

# 리포 루트 = scripts/demo/seed_demo.py에서 2단계 상위. 코퍼스 경로를 절대경로로 고정(CWD 무관).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"

# 데모/파일럿 문제 풀(멱등 적재·순서대로). 4문제만 시드하면 2~3문제 풀고 next-problem 후보가
# 고갈돼(NOT IN 제외) "추천 없음"→앱이 마지막 문항 폴백="같은 문제 반복" 체감(2026-07-22 실기기).
# answer 100% 보유 코퍼스만(완료 감지 verify_final_answer 필요)·전부 자체생성·WHYMATH_GENERATED
# (populate 위생 통과 실측). 첫 항목(손저작 v1)은 *필수*, 나머지는 best-effort(부재/실패 skip).
# 은행별 건수는 `docs/data/corpus_facts.md`의 `problem_bank.<은행 이름>`(v1·generated_v0·…).
_CORPORA: tuple[Path, ...] = (
    _CORPUS_ROOT / "problem_bank_v1" / "problems.jsonl",  # 손저작(필수·안정)
    _CORPUS_ROOT / "problem_bank_generated_v0" / "problems.jsonl",  # 단답(answer 100%)
    _CORPUS_ROOT / "problem_bank_misconception_mc_v0" / "problems.jsonl",  # 객관식(choices)
)


def main() -> int:
    """데모 문제 풀을 멱등 적재하고 종료 코드를 반환(0=성공·2=필수 코퍼스 부재/실패).

    여러 코퍼스를 순서대로 적재한다(멱등·slug upsert). 첫 항목(손저작 v1)은 필수라 실패 시 2를
    반환하고, 나머지는 best-effort(부재/실패는 경고만·데모는 v1만으로도 최소 동작). 조용한 무동작
    금지 — 각 코퍼스의 적재 결과를 명시 보고한다.
    """
    from whymath_backend.l1.problem_bank.populate import main as populate_main

    loaded_any = False
    for index, corpus in enumerate(_CORPORA):
        is_required = index == 0  # 첫 항목(v1)은 필수.
        if not corpus.exists():
            msg = f"[seed_demo] 코퍼스 부재: {corpus}"
            if is_required:
                print(msg + " — 필수 코퍼스라 중단.")
                return 2
            print(msg + " — best-effort skip.")
            continue
        print(f"[seed_demo] 적재 시작: {corpus}")
        code = populate_main(["--problems", str(corpus)])
        if code != 0:
            if is_required:
                print(f"[seed_demo] 필수 코퍼스 적재 실패(code={code}): {corpus} — 중단.")
                return code
            print(f"[seed_demo] 경고 — 적재 실패(code={code}·skip): {corpus}")
            continue
        loaded_any = True
    if not loaded_any:
        return 2
    print(
        "[seed_demo] 완료 — 데모 사용자는 콜백(/v1/auth/demo/callback) 최초 호출 시 "
        "lazy upsert된다(별도 시드 불필요)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
