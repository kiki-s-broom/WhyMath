#!/usr/bin/env python3
"""헌법 개정 채택 도우미 — **사람(Kiki)이** 실행한다 (CONST-02 · 헌법 제9조·제11조).

AI 세션이 찾은 정정·개정은 `docs/constitution_proposals/` 에 초안으로만 남는다(AI는
`constitution/` 을 고칠 수 없다). 이 도구는 Kiki가 그 초안을 읽고 채택하기로 했을 때
`constitution/` 에 **정확히 초안대로만** 반영한다. 손으로 복사·붙여넣기를 하면 생기는 사고
세 가지를 막기 위해 만들었다:

  ① 순서 사고 — A0003 정정안(rules_v1.0.1)은 규칙 14건 기준 파일이다. A0002(규칙 81건 병합)를
     먼저 반영한 뒤 그 파일을 통째로 복사하면 **규칙 81건이 조용히 사라진다**. 그래서 A0003은
     파일 복사가 아니라 `version` 줄과 `sources:` 절만 바꾸고, 규칙 목록이 그대로인지 단언한다.
  ② 인코딩 사고 — Windows PowerShell 5.1의 `Set-Content`는 BOM·CRLF를 붙인다. 이 도구는
     UTF-8(BOM 없음)·LF로만 쓴다.
  ③ 서명 누락 — 개정 기록의 상태·채택일·개정자 칸을 채워서 `constitution/amendments/` 에 둔다.

사용법 (저장소 최상위에서)
  python scripts/constitution/adopt_amendment.py A0003 --stage 2            # 미리보기(쓰지 않음)
  python scripts/constitution/adopt_amendment.py A0003 --stage 2 --apply    # 반영
  python scripts/constitution/adopt_amendment.py A0002                      # 미리보기
  python scripts/constitution/adopt_amendment.py A0002 --apply              # 반영
  python scripts/constitution/adopt_amendment.py A0004                      # 미리보기 (A0003 선행)
  python scripts/constitution/adopt_amendment.py A0004 --apply              # 반영

`--apply` 는 AI 세션(환경변수 CLAUDECODE 가 있는 셸)에서 실행하면 거부한다(exit 3) — 헌법
제9조의 이중 방어다. 미리보기는 읽기 전용이라 누구나 돌릴 수 있다.

반영 뒤 할 일(런북 docs/ops/coding_constitution_kiki_runbook.md 가 순서를 안내한다):
  python scripts/constitution/audit.py                         # 위헌 심사 — 차단 0건이어야
  python scripts/constitution/audit_ratchet.py --update-baseline  # 래칫 기준선을 새 상태로

종료 코드: 0 = 미리보기 통과 또는 반영 완료 / 1 = 전제 불충족(쓰지 않음) /
           2 = 인자 오류 / 3 = AI 세션에서 --apply 거부
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("⛔ PyYAML이 필요합니다: python -m pip install pyyaml")

ROOT = Path(__file__).resolve().parents[2]
CONST = ROOT / "constitution"
RULES = CONST / "rules.yaml"
STAGE = CONST / "STAGE"
CONSTITUTION = CONST / "CONSTITUTION.md"
AMENDMENTS = CONST / "amendments"
PROPOSALS = ROOT / "docs" / "constitution_proposals"
MERGE_RULES = ROOT / "scripts" / "constitution" / "merge_rules.py"

A0003_RULES = PROPOSALS / "rules_v1.0.1_sources_fixed.yaml"
A0003_DRAFT = PROPOSALS / "A0003_sources_registry_draft.md"
A0003_TARGET = "A0003_원본등록부정정.md"
A0002_CONSTITUTION = PROPOSALS / "CONSTITUTION_v1.1_A0002_proposed.md"
A0002_ADDITIONS = PROPOSALS / "rules_additions_v1.1.yaml"
A0002_DRAFT = PROPOSALS / "A0002_parts_II-VII_rules_draft.md"
A0002_TARGET = "A0002_파트II-VII규칙.md"
A0004_ADDITIONS = PROPOSALS / "rules_v1.0.2_sources_additions.yaml"
A0004_DRAFT = PROPOSALS / "A0004_sources_registry_additions_draft.md"
A0004_TARGET = "A0004_원본등록부3건추가.md"

SOURCE_ITEM = re.compile(r"^  - name:", re.M)
TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*:")
STATUS_LINE = re.compile(r"^- 상태: \*\*초안[^\n]*$", re.M)


class RefusalError(Exception):
    """전제 불충족 — 아무것도 쓰지 않고 멈춘다(exit 1)."""


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RefusalError(f"파일 없음: {path.relative_to(ROOT)}") from exc


def parse(text: str, label: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RefusalError(f"{label} YAML 형식 오류: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RefusalError(f"{label}: rules 목록을 읽지 못함")
    return data


def write(path: Path, text: str) -> None:
    """UTF-8(BOM 없음)·LF 로만 쓴다 — PowerShell Set-Content 의 BOM·CRLF 사고 방지."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def already_adopted(number: str) -> list[Path]:
    return sorted(AMENDMENTS.glob(f"{number}_*.md"))


def stamp(draft: str, adopter: str, today: str, extra: list[str]) -> str:
    """초안의 상태 줄을 '채택'으로 바꾸고 채택일·서명 칸을 채운다(각 치환은 정확히 1건)."""
    if len(STATUS_LINE.findall(draft)) != 1:
        raise RefusalError(
            "초안에서 '- 상태: **초안…' 줄을 정확히 1건 찾지 못함 — 초안 형식이 바뀌었다"
        )
    status = (
        f"- 상태: **채택** — 채택일 {today} · 개정자 {adopter} "
        "(초안 작성: AI 세션 · 채택: 사람 — 헌법 제11조)"
    )
    out = STATUS_LINE.sub(lambda _m: "\n".join([status, *extra]), draft)
    first, sep, rest = out.partition("\n")
    if first.startswith("# ") and first.endswith(" (초안)"):
        out = first[: -len(" (초안)")] + sep + rest  # 제목의 '(초안)' 표기를 뗀다
    out = out.replace("채택일: ____ (Kiki 기입)", f"채택일: {today}")
    out = out.replace("(서명란: ____)", f"(서명: {adopter})")
    return out


def split_sources(text: str) -> tuple[str, str]:
    """rules.yaml 텍스트를 최상위 `sources:` 줄 앞·뒤로 나눈다(바로 위 주석 블록은 앞쪽에 둔다)."""
    lines = text.splitlines(keepends=True)
    idx = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == "sources:"]
    if len(idx) != 1:
        raise RefusalError(f"최상위 'sources:' 줄이 정확히 1건이 아님({len(idx)}건)")
    at = idx[0]
    if any(TOP_KEY.match(line) for line in lines[at + 1 :]):
        raise RefusalError(
            "'sources:' 뒤에 다른 최상위 키가 있다 — sources 는 파일 마지막 절이어야 한다"
        )
    return "".join(lines[:at]), "".join(lines[at:])


def version_line(text: str) -> str:
    found = [line for line in text.splitlines() if line.startswith("version:")]
    if len(found) != 1:
        raise RefusalError(f"최상위 'version:' 줄이 정확히 1건이 아님({len(found)}건)")
    return found[0]


# ─────────────────────────── A0003 ───────────────────────────
def plan_a0003(stage_to: int | None, adopter: str, today: str) -> dict[Path, str]:
    """A0003(원본 등록부 정정)의 쓰기 계획 {경로: 새 내용}. 전제가 어긋나면 RefusalError."""
    if already_adopted("A0003"):
        raise RefusalError(f"A0003 이미 채택됨: {already_adopted('A0003')[0].name}")
    current_text = read(RULES)
    proposal_text = read(A0003_RULES)
    current = parse(current_text, "constitution/rules.yaml")
    proposal = parse(proposal_text, "정정안")

    head, _old_sources = split_sources(current_text)
    _p_head, new_sources = split_sources(proposal_text)
    new_text = head.replace(version_line(current_text), version_line(proposal_text), 1)
    new_text = new_text + new_sources

    merged = parse(new_text, "반영 결과")
    # 규칙 목록은 **현재 것 그대로**여야 한다 — A0002를 먼저 반영했어도 규칙이 사라지지 않는다
    if merged["rules"] != current["rules"]:
        raise RefusalError("반영 결과의 규칙 목록이 현재와 다르다 — 쓰지 않음")
    if merged.get("sources") != proposal.get("sources"):
        raise RefusalError("반영 결과의 원본 등록부가 정정안과 다르다 — 쓰지 않음")
    if merged.get("version") != proposal.get("version"):
        raise RefusalError("반영 결과의 version 이 정정안과 다르다 — 쓰지 않음")

    plan = {RULES: new_text}
    extra = []
    if stage_to is not None:
        now = int(read(STAGE).strip() or "0")
        if stage_to != now + 1:
            raise RefusalError(
                f"단계는 한 번에 한 칸만 올린다(부록 C) — 현재 {now} → 요청 {stage_to}"
            )
        plan[STAGE] = f"{stage_to}\n"
        extra.append(f"- 함께 반영: 이식 단계 STAGE {now} → {stage_to}")
    plan[AMENDMENTS / A0003_TARGET] = stamp(read(A0003_DRAFT), adopter, today, extra)
    return plan


# ─────────────────────────── A0002 ───────────────────────────
def _is_subsequence(needles: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(n == h for h in it) for n in needles)


def plan_a0002(adopter: str, today: str) -> dict[Path, str]:
    """A0002(파트 II~VII 조문 신설 + 규칙 81건)의 헌법·개정 기록 쓰기 계획. 규칙 병합은 별도."""
    if already_adopted("A0002"):
        raise RefusalError(f"A0002 이미 채택됨: {already_adopted('A0002')[0].name}")
    current = read(CONSTITUTION)
    proposed = read(A0002_CONSTITUTION)
    if "**제7조의2(" in current:
        raise RefusalError("헌법 본문에 이미 제7조의2가 있다 — 개정 기록 없이 조문이 들어간 상태")
    # 제안본은 현재 본문을 **덧붙이기만** 해야 한다(판 표기 줄 제외) — 기존 조문 변경은 별도 개정
    base_lines = [ln for ln in current.splitlines() if ln.strip() and not ln.startswith("- 판:")]
    if not _is_subsequence(base_lines, proposed.splitlines()):
        raise RefusalError(
            "제안본이 현재 헌법 본문을 그대로 포함하지 않는다(기존 문구가 바뀌었거나 본문이 "
            "제안본의 기준과 다르다) — A0002는 조문 신설만 다룬다. 세션에 제안본 재생성을 요청한다"
        )
    for n in range(1, 12):
        if f"**제{n}조(" not in proposed:
            raise RefusalError(f"제안본에 제{n}조가 없다")
    return {
        CONSTITUTION: proposed,
        AMENDMENTS / A0002_TARGET: stamp(read(A0002_DRAFT), adopter, today, []),
    }


# ─────────────────────────── A0004 ───────────────────────────
def _exists(path: Path) -> bool:
    """Path.exists() 는 권한 거부(EACCES)를 False 로 돌려주지 않고 예외로 올린다 — 거부로 바꾼다."""
    try:
        return path.exists()
    except OSError as exc:
        raise RefusalError(f"경로 접근 불가({type(exc).__name__}): {path}") from exc


def plan_a0004(adopter: str, today: str) -> dict[Path, str]:
    """A0004(원본 등록부 3건 추가)의 쓰기 계획. 규칙·단계·조문은 불변이고 sources 끝에 덧붙인다.

    A0003 위에 얹는 개정이라 A0003 채택을 전제로 확인한다(CONST-12 ⑩).
    """
    if already_adopted("A0004"):
        raise RefusalError(f"A0004 이미 채택됨: {already_adopted('A0004')[0].name}")
    if not already_adopted("A0003"):
        raise RefusalError(
            "A0003 미채택 — A0004 는 A0003 위에 얹는 개정이다. 먼저 A0003 을 채택한다"
        )
    current_text = read(RULES)
    current = parse(current_text, "constitution/rules.yaml")
    split_sources(current_text)  # sources 가 파일 마지막 절인지 확인(덧붙임의 전제)

    additions_text = read(A0004_ADDITIONS).replace("\r\n", "\n")
    first_item = SOURCE_ITEM.search(additions_text)
    if first_item is None:
        raise RefusalError("추가분에서 '  - name:' 항목을 찾지 못함 — 추가분 형식이 바뀌었다")
    body = additions_text[first_item.start() :].rstrip("\n") + "\n"  # 머리 주석(초안 안내)은 뗀다
    try:
        entries = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        raise RefusalError(f"추가분 YAML 형식 오류: {type(exc).__name__}") from exc
    if (
        not isinstance(entries, list)
        or not entries
        or not all(isinstance(e, dict) and e.get("name") and e.get("path") for e in entries)
    ):
        raise RefusalError("추가분 항목 형식 오류 — 모든 항목에 name·path 가 있어야 한다")

    names = [e["name"] for e in entries]
    have = list(current.get("sources") or [])
    taken = {s.get("name") for s in have}
    dup = sorted((set(names) & taken) | {n for n in names if names.count(n) > 1})
    if dup:
        raise RefusalError(f"이미 등록됐거나 추가분 안에서 겹치는 원본 이름: {dup}")
    for e in entries:  # 존재하지 않는 경로를 등록하면 위헌 심사 R4-01 이 새 차단 사유를 낸다
        if not e.get("external") and not _exists(ROOT / e["path"]):
            raise RefusalError(f"등록할 원본 경로가 저장소에 없다: {e['path']}")

    new_text = current_text.rstrip("\n") + "\n\n" + body
    merged = parse(new_text, "반영 결과")
    if merged["rules"] != current["rules"]:
        raise RefusalError("반영 결과의 규칙 목록이 현재와 다르다 — 쓰지 않음")
    if merged.get("sources") != have + entries:
        raise RefusalError("반영 결과의 원본 등록부가 '현재 + 추가분'과 다르다 — 쓰지 않음")
    if set(merged) != set(current) or any(
        merged[k] != v for k, v in current.items() if k != "sources"
    ):
        raise RefusalError("sources 외 항목(version·stage 설명 등)이 바뀌었다 — 쓰지 않음")

    extra = [f"- 함께 반영: 원본 등록부 {len(have)}건 → {len(have) + len(entries)}건"]
    return {
        RULES: new_text,
        AMENDMENTS / A0004_TARGET: stamp(read(A0004_DRAFT), adopter, today, extra),
    }


def _decode(raw: bytes, label: str) -> str:
    """자식 출력을 UTF-8 로 명시 해독한다. 실패는 삼키지 않고 거부로 올린다 (CONST-12).

    text=True·encoding 을 subprocess 에 맡기면 해독이 reader 스레드 안에서 일어나, 실패가 스레드
    트레이스로만 찍히고 출력은 조용히 사라진다 — 호출자는 빈 문자열을 정상으로 읽는다.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RefusalError(
            f"{label} 해독 실패({type(exc).__name__}) — 자식 출력이 UTF-8 이 아니다"
        ) from exc


def run_merge(apply: bool) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(MERGE_RULES), str(A0002_ADDITIONS)]
    if apply:
        cmd += ["--apply", "--bump-stage-note"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=120)
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        _decode(proc.stdout, "규칙 병합 stdout"),
        _decode(proc.stderr, "규칙 병합 stderr"),
    )


# ─────────────────────────── 실행 ───────────────────────────
def show(plan: dict[Path, str]) -> None:
    for path, text in plan.items():
        rel = path.relative_to(ROOT).as_posix()
        state = "수정" if path.exists() else "신규"
        print(f"  · {state} {rel} ({len(text.encode('utf-8'))}바이트)")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="헌법 개정 채택 도우미(사람 전용)")
    ap.add_argument("amendment", choices=["A0003", "A0002", "A0004"])
    ap.add_argument("--stage", type=int, choices=range(2, 7), help="A0003과 함께 올릴 단계")
    ap.add_argument("--apply", action="store_true", help="실제 반영(없으면 미리보기)")
    ap.add_argument("--adopter", default="Kiki", help="개정자 이름(기본 Kiki)")
    args = ap.parse_args()

    if args.apply and os.environ.get("CLAUDECODE"):
        print(
            "⛔ AI 세션(CLAUDECODE)에서는 --apply 를 실행할 수 없다 — 헌법 제9조·제11조. "
            "Kiki의 PowerShell 창에서 실행한다.",
            file=sys.stderr,
        )
        print("ADOPT_RESULT=refused_ai_session")
        return 3
    if args.amendment != "A0003" and args.stage is not None:
        print("⛔ --stage 는 A0003 과 함께만 쓴다", file=sys.stderr)
        return 2

    today = date.today().isoformat()
    try:
        if args.amendment == "A0003":
            plan = plan_a0003(args.stage, args.adopter, today)
        elif args.amendment == "A0004":
            plan = plan_a0004(args.adopter, today)
        else:
            plan = plan_a0002(args.adopter, today)
            preview = run_merge(apply=False)
            print(preview.stdout.strip())
            if preview.returncode != 0:
                raise RefusalError(
                    f"규칙 병합 미리보기 실패(exit {preview.returncode}): {preview.stderr}"
                )
    except RefusalError as exc:
        print(f"⛔ 전제 불충족 — 아무것도 쓰지 않음: {exc}", file=sys.stderr)
        print("ADOPT_RESULT=refused")
        return 1

    print(f"{args.amendment} 채택 계획 ({'반영' if args.apply else '미리보기'}):")
    show(plan)
    if args.amendment == "A0004":  # 등록부가 몇 건에서 몇 건이 되는지 눈으로 확인(CONST-12 ⑩)
        before = len(parse(read(RULES), "constitution/rules.yaml").get("sources") or [])
        after = len(parse(plan[RULES], "반영 결과").get("sources") or [])
        print(f"SOURCES_PLAN={before}->{after}")
    if not args.apply:
        print("ADOPT_RESULT=preview")
        print("반영하려면 같은 명령에 --apply 를 붙인다.")
        return 0

    if args.amendment == "A0002":
        try:
            merged = run_merge(apply=True)
        except RefusalError as exc:  # 해독 실패도 쓰지 않고 멈춘다(헌법 본문 쓰기 전)
            print(f"⛔ 규칙 병합 출력을 읽지 못함 — 헌법 본문은 쓰지 않음: {exc}", file=sys.stderr)
            print("ADOPT_RESULT=refused")
            return 1
        print(merged.stdout.strip())
        if merged.returncode != 0:
            print(f"⛔ 규칙 병합 실패 — 헌법 본문은 쓰지 않음: {merged.stderr}", file=sys.stderr)
            print("ADOPT_RESULT=refused")
            return 1
    for path, text in plan.items():
        write(path, text)
    rules = parse(read(RULES), "constitution/rules.yaml")
    print(f"RULES_COUNT={len(rules['rules'])}")
    print(f"SOURCES_COUNT={len(rules.get('sources') or [])}")
    print(f"STAGE_NOW={read(STAGE).strip()}")
    print(f"AMENDMENTS={','.join(p.name for p in sorted(AMENDMENTS.glob('A*.md')))}")
    print("ADOPT_RESULT=applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
