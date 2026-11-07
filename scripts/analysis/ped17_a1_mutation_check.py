"""A1 뮤테이션 검증 하네스 — 가드가 "있다"가 아니라 "잡는다"를 실측한다 (CLAUDE.md 실패 주입 원칙).

각 뮤테이션은 소스 한 곳을 일부러 망가뜨린 뒤 지정한 테스트를 돌려 **RED(종료코드 1)가 나는지**
본다.
GREEN으로 남으면 그 보호는 위장이다("생존").

하네스 자체의 신뢰를 위해 매 주입마다 다음을 단언한다(주입 자체의 실재):
  ① 치환 대상 문자열이 원본에 정확히 1건 있다(0건이면 주입이 조용히 실패한 것).
  ② 치환 결과가 원본과 다르다.
  ③ 테스트 실행 뒤 `cp` 백업으로 원복하고 **바이트 동일**을 확인한다(git 원복 금지 — 미커밋분 소실
    방지).

사용: 저장소 루트에서
    WHYMATH_DATABASE_URL=... python scripts/analysis/ped17_a1_mutation_check.py [mutation_id ...]
종료코드: 0 = 모든 뮤테이션 검출(전건 RED) / 1 = 생존 있음 또는 하네스 오류
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # scripts/analysis/ → 저장소 루트
PY = sys.executable
PYTEST = [
    PY,
    "-m",
    "pytest",
    "-c",
    "src/backend/pyproject.toml",
    "--rootdir=src/backend",
    "-q",
    "-x",
    "-p",
    "no:randomly",
]

LIFECYCLE = "src/backend/whymath_backend/l1/concept_content/lifecycle.py"
SCHEMA = "src/backend/whymath_backend/schema/concept_lifecycle.py"
CONTENT_SUPPLY = "src/backend/whymath_backend/l4/content_supply.py"
STUDY = "src/backend/whymath_backend/api/study.py"
EXPOSURE = "src/backend/whymath_backend/l2/concept_exposure.py"
UNIT = "tests/backend/l1/test_concept_lifecycle.py"


@dataclass(frozen=True)
class Mutation:
    mid: str
    desc: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M1",
        "전환표에 지름길(초안→공개됨)을 추가한다",
        SCHEMA,
        "    (_S.WITHDRAWN, _S.DRAFT): frozenset({_V.REGENERATE}),\n",
        "    (_S.WITHDRAWN, _S.DRAFT): frozenset({_V.REGENERATE}),\n"
        "    (_S.DRAFT, _S.PUBLISHED): frozenset({_V.D5_STAGED_ROLLOUT}),\n",
        (UNIT,),
    ),
    Mutation(
        "M2",
        "경로 검사를 제거한다(쌍만 맞으면 어떤 경로든 통과)",
        LIFECYCLE,
        "    if via not in allowed_vias:\n",
        "    if False:\n",
        (UNIT,),
    ),
    Mutation(
        "M3",
        "긴급 정지의 Kiki 전용 검사를 제거한다",
        LIFECYCLE,
        "    if via in KIKI_ONLY_VIA and changed_by_kind is not ChangedByKind.KIKI:\n",
        "    if False:\n",
        (UNIT,),
    ),
    Mutation(
        "M4",
        "상태는 바꾸되 기록 행을 추가하지 않는다",
        LIFECYCLE,
        "    session.add(record)\n",
        "    pass\n",
        (UNIT,),
    ),
    Mutation(
        "M5",
        "빈 사유 검사를 제거한다",
        LIFECYCLE,
        "    if not why:\n",
        "    if False:\n",
        (UNIT,),
    ),
    Mutation(
        "M6",
        "공개 술어에서 '공개됨' 확인을 제거한다",
        LIFECYCLE,
        "    if lifecycle_status != ConceptLifecycleState.PUBLISHED.value:\n        return False\n",
        "    if False:\n        return False\n",
        (UNIT,),
    ),
    Mutation(
        "M7",
        "사람 검수 행의 review_status 유지 조건을 제거한다(재적재 강등이 학생에게 안 닿음)",
        LIFECYCLE,
        "        return is_supply_eligible(review_status)\n",
        "        return True\n",
        (UNIT, "tests/backend/l4/test_content_supply.py"),
    ),
    Mutation(
        "M8",
        "AI 생성 행에서 사람의 rejected 판정을 무시한다",
        LIFECYCLE,
        "        return review_status != _REJECTED_STATUS\n",
        "        return True\n",
        (UNIT,),
    ),
    Mutation(
        "M9",
        "학생 경로 관문을 옛 술어(review_status만)로 되돌린다",
        CONTENT_SUPPLY,
        "    if not row_is_student_visible(row):\n"
        "        return ContentResolution(None, REASON_UNREVIEWED, row.code, via, candidates)\n",
        "    if row.review_status != 'reviewed':\n"
        "        return ContentResolution(None, REASON_UNREVIEWED, row.code, via, candidates)\n",
        ("tests/backend/l4/test_content_supply.py", "tests/backend/api/test_study_endpoint.py"),
    ),
    Mutation(
        "M10",
        "역조회 후보 선택에서 공개 여부를 보지 않는다",
        CONTENT_SUPPLY,
        "        row = next((r for r in found if row_is_student_visible(r)), found[0])\n",
        "        row = found[0]\n",
        ("tests/backend/l4/test_content_supply.py",),
    ),
    Mutation(
        "M11",
        "/study가 노출 기록을 남기지 않는다",
        STUDY,
        "    await record_concept_exposure(\n",
        "    (lambda *_a, **_k: None)(\n",  # 문법이 유효한 무동작 대체(await 없음)
        ("tests/backend/api/test_study_endpoint.py",),
    ),
    Mutation(
        "M12",
        "노출 기록이 가명이 아니라 원본 user_id를 저장한다",
        EXPOSURE,
        "        student_pseudonym=student_pseudonym(user_id, settings=settings),\n",
        "        student_pseudonym=str(user_id),\n",
        ("tests/backend/api/test_study_endpoint.py", "tests/backend/l2/test_concept_exposure.py"),
    ),
)


def _run(mut: Mutation) -> tuple[bool, str]:
    """뮤테이션 1건 실행. (검출 여부, 메모)를 돌려준다. 원복은 finally에서 항상 한다."""
    path = ROOT / mut.file
    original = path.read_bytes()
    backup = Path(tempfile.mkdtemp(prefix="a1_mut_")) / path.name
    shutil.copyfile(path, backup)  # cp 백업 — git 원복 금지
    try:
        text = original.decode("utf-8")
        count = text.count(mut.old)
        if count != 1:
            return False, f"하네스 오류: 치환 대상이 {count}건(1건이어야 함) — 주입 실패"
        mutated = text.replace(mut.old, mut.new)
        if mutated == text:
            return False, "하네스 오류: 치환 결과가 원본과 같다 — 주입 실패"
        path.write_bytes(mutated.encode("utf-8"))
        missing = [t for t in mut.tests if not (ROOT / t).exists()]
        if missing:
            return False, f"하네스 오류: 테스트 파일 없음 {missing}"
        # 인코딩을 명시한다(HARN-19) — Windows 한국어 로케일의 기본 cp949로 pytest 출력을
        # 디코드하지 않게.
        proc = subprocess.run(
            [*PYTEST, *mut.tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        detected = proc.returncode == 1  # 1 = 테스트 실패(RED). 0 = 생존, 2+ = 수집/설정 오류.
        tail = [ln for ln in proc.stdout.splitlines() if ("passed" in ln or "failed" in ln)][-1:]
        note = tail[0] if tail else f"rc={proc.returncode}"
        if proc.returncode not in (0, 1):
            return False, f"하네스 오류: pytest rc={proc.returncode} ({note})"
        return detected, note
    finally:
        shutil.copyfile(backup, path)
        if path.read_bytes() != original:
            print(f"!! 원복 실패: {mut.file}", file=sys.stderr)
            raise SystemExit(2)


def main(argv: list[str]) -> int:
    wanted = set(argv) if argv else None
    survivors: list[str] = []
    for mut in MUTATIONS:
        if wanted and mut.mid not in wanted:
            continue
        detected, note = _run(mut)
        print(f"{mut.mid:<4} {'검출(RED)' if detected else '생존/오류':<9} {mut.desc}  [{note}]")
        if not detected:
            survivors.append(mut.mid)
    print(f"\n생존/오류: {survivors if survivors else '없음'}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
