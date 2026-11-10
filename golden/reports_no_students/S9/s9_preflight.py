"""S9 사전 검사 — 학생 세션을 시작하기 전에 이 트리의 채점기가 Kiki 결정대로 동작하는지 본다.

Kiki 결정(2026-11-10): 학생이 `-3+4=1`처럼 풀이식과 답을 함께 쓰면 정답으로 채점한다
(S8 계약 변경 제안 ⑬ · S8 세션의 GOLD-08이 구현). 이 검사는 커밋 해시가 아니라 **동작**을 본다.

- EQ_FORM_GRADED  : LF-02(정답 1)에 `-3+4=1` → 정답이어야 한다(수정 전 main에서는 False)
- PLAIN_OK        : LF-02에 `1` → 정답(기존 동작 유지)
- WRONG_EQ_REJECTED: LF-02에 `-3+4=2` → 오답(마지막 값이 틀리면 여전히 틀림)
- GRADE_FROM_THIS_TREE: 실제로 임포트된 grade.py가 이 스크립트가 든 트리의 것인가(실행 코드 출처)

세 판정과 출처가 모두 True면 exit 0, 하나라도 False면 exit 1.
코드를 고치지 않는다 — 읽고 부르기만 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 이 파일 위치: <트리>/golden/reports_no_students/S9/s9_preflight.py → <트리>/src/backend
_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
sys.path.insert(0, str(_BACKEND))

import golden.grade as grade  # noqa: E402 — 위에서 경로를 넣은 뒤에 임포트해야 한다
from golden.problems import load_problems  # noqa: E402


def main() -> int:
    """세 판정과 실행 코드 출처를 출력하고 종료 코드를 돌려준다."""
    problems = {p["id"]: p for p in load_problems()}
    lf02 = problems["LF-02"]
    eq_form = grade.is_correct(lf02, "-3+4=1")
    plain = grade.is_correct(lf02, "1")
    wrong_rejected = not grade.is_correct(lf02, "-3+4=2")
    grade_file = Path(grade.__file__).resolve()
    from_this_tree = grade_file.is_relative_to(_BACKEND)

    print("EQ_FORM_GRADED=" + str(eq_form) + "  (기대 True — 풀이식=답을 정답 처리)")
    print("PLAIN_OK=" + str(plain) + "  (기대 True)")
    print("WRONG_EQ_REJECTED=" + str(wrong_rejected) + "  (기대 True)")
    print("GRADE_FILE=" + str(grade_file))
    print("GRADE_FROM_THIS_TREE=" + str(from_this_tree) + "  (기대 True)")
    ok = eq_form and plain and wrong_rejected and from_this_tree
    print("PREFLIGHT_OK=" + str(ok))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
