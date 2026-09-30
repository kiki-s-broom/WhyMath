"""HARN-193 뮤테이션 하네스 — 미머지 게이트 부착 스캔이 *실제로* 결함을 잡는지 주입으로 확인한다.

정상 입력에서 초록인 테스트는 보호의 증거가 아니다. 이 하네스는 스캔·배선의 각 절을 하나씩 깨뜨린
뒤 `tests/harness/test_gate_attach_claim_gap.py`가 RED가 되는지 본다.

매 회 지키는 것(CLAUDE.md 실패 주입 규칙):
  · **앵커 1건** — 치환 대상이 정확히 1건이어야 한다(0건이면 조용히 아무것도 안 하고, 2건이면
    엉뚱한 자리를 고친다).
  · **주입 실재** — 치환 후 원문과 달라야 한다(안 들어간 주입은 '검출'처럼 보인다).
  · **쓴 내용 재확인** — 디스크에서 다시 읽어 치환 결과와 같은지 본다.
  · **원복 바이트 동일** — 실행 전 바이트 백업을 그대로 되돌리고 sha256 일치를 단언한다.
    (`git checkout`으로 원복하지 않는다 — 미커밋 구현분까지 HEAD로 되돌린다.)
  · **대조군** — 주입 없는 실행이 먼저 GREEN이어야 이하의 RED가 의미를 갖는다.
  · 실행마다 대상 모듈 `.pyc`를 지우고 `PYTHONDONTWRITEBYTECODE=1`로 낡은 바이트코드를 배제한다.

종료 코드: 0 = 대조군 GREEN이고 기대한 뮤테이션이 전부 검출됨(생존 0), 1 = 생존 뮤테이션 있음,
2 = 하네스 자체 오류(앵커·주입·원복 위반 포함).

사용: python3 scripts/analysis/mutate_gate_attach_guards.py [--only M03,M05]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "harness"
TEST_FILE = "tests/harness/test_gate_attach_claim_gap.py"

RC = HARNESS / "remote_claims.py"
BL = HARNESS / "backlog.py"
RP = HARNESS / "report.py"


@dataclass(frozen=True)
class Mutation:
    mid: str
    target: Path
    anchor: str
    replacement: str
    what: str
    # 동치 뮤테이션(동작이 바뀌지 않는다)은 생존이 정상이다 — 왜 동치인지 `what`에 적는다.
    equivalent: bool = False


MUTATIONS: tuple[Mutation, ...] = (
    # ── 스캔 본체(remote_claims.py) ──
    Mutation(
        "M01",
        RC,
        "                if gate_id in known:\n",
        "                if False and gate_id in known:\n",
        "이미 아는 게이트도 부착으로 센다(차집합 무력화)",
    ),
    Mutation(
        "M02",
        RC,
        "known = trunk_gates[tid] | set(tasks[tid])",
        "known = set(tasks[tid])",
        "트렁크 쪽 기준선 제거 — 머지됐지만 안 지워진 브랜치를 영구 오차단",
    ),
    Mutation(
        "M03",
        RC,
        "known = trunk_gates[tid] | set(tasks[tid])",
        "known = trunk_gates[tid]",
        "로컬 쪽 기준선 제거 — classify_todo가 이미 판정한 게이트를 중복 보고",
    ),
    Mutation(
        "M04",
        RC,
        'if trunk_state[gate_id] in ("cleared", "waived"):',
        "if False:",
        "트렁크가 통과시킨 게이트도 부착으로 센다(과잉 차단)",
    ),
    Mutation(
        "M05",
        RC,
        'if trunk_state[gate_id] in ("cleared", "waived"):',
        'if trunk_state[gate_id] in ("cleared", "waived", ""):',
        "'트렁크에 정의 없음'을 통과로 취급 — 이번 사고(게이트가 브랜치에서 신설)를 면제",
    ),
    Mutation(
        "M06",
        RC,
        "skip_refs = {trunk_ref, *(REMOTE_REF_PREFIX + b for b in exclude_branches)}",
        "skip_refs = {trunk_ref}",
        "세션 자신의 브랜치를 제외하지 않는다",
    ),
    Mutation(
        "M07",
        RC,
        "skip_refs = {trunk_ref, *(REMOTE_REF_PREFIX + b for b in exclude_branches)}",
        "skip_refs = {*(REMOTE_REF_PREFIX + b for b in exclude_branches)}",
        "트렁크 ref를 제외하지 않는다 — 트렁크만 있는 캐시가 '다른 브랜치 있음'으로 읽힌다",
    ),
    Mutation(
        "M08",
        RC,
        "if len(blobs) != len(pairs):",
        "if False:",
        "cat-file 출력 정렬 어긋남 검사 제거 — 판정 불가 대신 다른 오류 상태로 샌다",
    ),
    Mutation(
        "M09",
        RC,
        'return found, "truncated" if truncated else "ok"',
        'return found, "ok"',
        "브랜치 상한 초과를 ok로 위장",
    ),
    Mutation(
        "M10", RC, "refs = wanted[:max_refs]", "refs = wanted", "상한을 무시 — truncated 판정 불능"
    ),
    Mutation(
        "M11",
        RC,
        'for gate_id in _top_level_list_field(blob, "requires_gates"):',
        'for gate_id in _top_level_list_field(blob, "depends_on"):',
        "브랜치 사본에서 엉뚱한 필드를 읽는다",
    ),
    Mutation(
        "M12",
        RC,
        'tid: set(_top_level_list_field(blob, "requires_gates")) if blob is not None else set()',
        'tid: set(_top_level_list_field(blob, "depends_on")) if blob is not None else set()',
        "트렁크 기준선을 엉뚱한 필드에서 읽는다(트렁크는 항상 '게이트 없음')",
    ),
    Mutation(
        "M13",
        RC,
        "trunk_gate_state=trunk_state[gate_id],",
        "trunk_gate_state=branch_state[(ref, gate_id)],",
        "트렁크 상태 자리에 브랜치 상태를 싣는다(미머지 clear를 트렁크 clear로 오독)",
    ),
    # ── start 배선(backlog.py) ──
    Mutation(
        "M14",
        BL,
        "            if attached:\n                lines = [\n",
        "            if False and attached:\n                lines = [\n",
        "start가 발견분을 무시하고 착수시킨다",
    ),
    Mutation(
        "M15",
        BL,
        '"start_ignored_unmerged_gate_attach",',
        '"start_ignored_unmerged_gate",',
        "우회 사유 이벤트의 이름이 바뀐다(감사 추적 단절)",
    ),
    Mutation(
        "M16",
        BL,
        "({done_status}) — 타 세션이 이 태스크에 게이트를 ",
        "(?) — 타 세션이 이 태스크에 게이트를 ",
        "fetch 실패 시 게이트 부착 판정 불가 경고에서 원인 상태를 지운다",
    ),
    Mutation(
        "M17",
        BL,
        '            elif gate_status != "ok":\n',
        "            elif False:\n",
        "start가 스캔 실패를 무증상으로 넘긴다",
    ),
    Mutation(
        "M18",
        BL,
        "                else:\n                    return _fail(message)\n"
        '            elif gate_status != "ok":',
        "                else:\n                    pass\n" '            elif gate_status != "ok":',
        "start의 거부가 우회 플래그 없이도 통과한다",
    ),
    # ── next 배선(backlog.py) ──
    Mutation(
        "M19",
        BL,
        "            ready = [t for t in ready if t.id not in gate_map]\n",
        "            pass\n",
        "next가 발견분을 후보에서 빼지 않는다",
    ),
    Mutation(
        "M20",
        BL,
        '            if gate_status != "ok":\n',
        "            if False:\n",
        "next가 스캔 실패를 무증상으로 넘긴다",
    ),
    # ── brief 배선(backlog.py · report.py) ──
    Mutation(
        "M21",
        BL,
        "                gate_attach_excluded = {\n                    tid:",
        "                gate_attach_excluded = {} and {\n                    tid:",
        "brief가 발견분을 버린다",
    ),
    Mutation(
        "M22",
        BL,
        "            gate_attach_excluded=gate_attach_excluded,\n",
        "            gate_attach_excluded=None,\n",
        "brief가 계산한 제외 목록을 render_brief에 넘기지 않는다(배선 단절)",
    ),
    Mutation(
        "M23",
        RP,
        "        ready = [t for t in ready if t.id not in gate_attach_excluded]\n",
        "        pass\n",
        "render_brief가 제외 대상을 후보에서 빼지 않는다",
    ),
    Mutation(
        "M24",
        RP,
        '    if gate_attach_status not in ("ok", "disabled"):',
        "    if False:",
        "render_brief가 스캔 실패를 stdout에 싣지 않는다(훅은 stderr를 버린다)",
    ),
    Mutation(
        "M25",
        RP,
        "⛔ 후보 제외 {task_id}",
        "⛔ 제외 {task_id}",
        "제외 이유 줄의 문구가 바뀐다(사라진 후보를 세션이 다시 조사하게 됨)",
    ),
    # ── shallow·단일 브랜치 클론 — '0개를 훑었다'는 '없다'가 아니다 ──
    Mutation(
        "M26",
        RC,
        "        if not wanted and not (fetch or refs_fresh):\n",
        "        if False:\n",
        "다른 브랜치를 0개 훑고도 ok를 돌려준다(shallow 클론에서 측정 실패가 '부착 없음'으로 위장)",
    ),
    Mutation(
        "M27",
        RC,
        "        if not wanted and not (fetch or refs_fresh):\n",
        "        if not wanted and not fetch:\n",
        "직전에 fetch한 호출자(start)의 브랜치 0개까지 no_refs로 — 과잉 경고",
    ),
    Mutation(
        "M28",
        BL,
        "                refs_fresh=True,  # 위 done 스캔의 fetch=True가 방금 ref를 최신화했다\n",
        "",
        "start가 refs_fresh 선언을 빠뜨린다 — 브랜치 0개 저장소에서 매 start마다 과잉 경고",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests() -> tuple[int, str]:
    """신규 테스트를 실행한다. 첫 실패에서 멈춘다(-x) — 검출 판정에는 한 건이면 충분하다."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for target in (RC, BL, RP):
        cache = target.parent / "__pycache__"
        if cache.is_dir():
            for pyc in cache.glob(f"{target.stem}.*.pyc"):
                pyc.unlink()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            TEST_FILE,
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",  # HARN-19 — 로케일(cp949) 디코드 금지(pytest 출력에 한글이 섞인다)
        errors="replace",
        timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def failed_tests(output: str) -> list[str]:
    return [
        line.split(" ", 1)[1].split("::", 2)[-1]
        for line in output.splitlines()
        if line.startswith("FAILED ")
    ]


class HarnessError(RuntimeError):
    """앵커·주입·원복 규칙 위반 — 결과를 신뢰할 수 없으므로 종료 코드 2."""


def apply_and_run(m: Mutation) -> tuple[int, str]:
    original_bytes = m.target.read_bytes()
    original = original_bytes.decode("utf-8")
    before = hashlib.sha256(original_bytes).hexdigest()
    try:
        if original.count(m.anchor) != 1:
            raise HarnessError(
                f"{m.mid}: 앵커가 1건이 아니다({original.count(m.anchor)}건): {m.anchor!r}"
            )
        mutated = original.replace(m.anchor, m.replacement)
        if mutated == original:
            raise HarnessError(f"{m.mid}: 주입이 들어가지 않았다(치환 결과가 원문과 같다)")
        m.target.write_bytes(mutated.encode("utf-8"))
        if m.target.read_bytes().decode("utf-8") != mutated:
            raise HarnessError(f"{m.mid}: 쓴 내용이 디스크에서 다시 읽은 내용과 다르다")
        return run_tests()
    finally:
        m.target.write_bytes(original_bytes)  # 바이트 백업 그대로 복원
        if hashlib.sha256(m.target.read_bytes()).hexdigest() != before:
            raise HarnessError(f"{m.mid}: 원복이 바이트 동일하지 않다 — 즉시 중단")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", default="", help="쉼표로 구분한 뮤테이션 ID만 실행(예: M03,M05)")
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    selected = [m for m in MUTATIONS if not only or m.mid in only]
    if not selected:
        print("선택된 뮤테이션이 없다", file=sys.stderr)
        return 2

    snapshot = {p: sha256(p) for p in (RC, BL, RP)}
    try:
        rc, out = run_tests()
        if rc != 0:
            print(
                "대조군(주입 없음)이 GREEN이 아니다 — 이하 RED는 의미가 없다\n" + out[-2000:],
                file=sys.stderr,
            )
            return 2
        print("대조군 GREEN (주입 없음)")

        survived: list[Mutation] = []
        unexpected_kill: list[Mutation] = []
        for m in selected:
            rc, out = apply_and_run(m)
            killed = rc != 0
            tag = "RED  " if killed else "GREEN"
            names = ", ".join(failed_tests(out)) or "-"
            expect = "(동치·생존 정상)" if m.equivalent else ""
            print(f"{tag} {m.mid} {m.what} {expect}\n        검출 테스트: {names}")
            if not killed and not m.equivalent:
                survived.append(m)
            if killed and m.equivalent:
                unexpected_kill.append(m)

        after = {p: sha256(p) for p in snapshot}
        if after != snapshot:
            print("하네스 종료 시점의 대상 파일이 시작 시점과 다르다", file=sys.stderr)
            return 2
        real = [m for m in selected if not m.equivalent]
        equivalents = len(selected) - len(real)
        print(f"\n생존 {len(survived)}건 / 검출 대상 {len(real)}건 (동치 {equivalents}건 별도)")
        print("대상 파일 sha256 시작·종료 일치")
        for m in survived:
            print(f"  생존: {m.mid} — {m.what}")
        for m in unexpected_kill:
            print(f"  동치로 표기했으나 검출됨: {m.mid} — 동치 판정을 재검토하라")
        return 1 if survived or unexpected_kill else 0
    except HarnessError as exc:
        print(f"하네스 오류: {exc}", file=sys.stderr)
        return 2
    finally:
        # 어떤 경로로 끝나도 대상 파일이 시작 시점과 같은지 마지막으로 확인한다.
        drift = [p.name for p, digest in snapshot.items() if sha256(p) != digest]
        if drift:
            print(f"경고: 대상 파일이 시작 시점과 다르다: {drift}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
