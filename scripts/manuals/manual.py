#!/usr/bin/env python3
"""업무 매뉴얼(manuals/) 구조 검사기 + 완료 조건 실행기 (HARN-316).

방법론 정본: docs/standards/agent_manual_method.md

하위 명령
  lint                       manuals/ 전수 구조 검사 (exit 0 = 전건 통과, 1 = 위반 있음)
  verify <id> [--arg k=v]    매뉴얼의 완료 조건(verify) 중 cmd 항목을 실제로 실행하고,
                             read·human 항목은 "에이전트가 증거를 대야 할 항목"으로 나열한다
                             (exit 0 = cmd 전건 통과, 1 = 실패·인자 누락, 2 = 매뉴얼 없음)
  list                       매뉴얼 목록과 준비 상태

무엇을 막는가
  - 완료 조건이 "확인 방법" 없이 적혀 있어 자체 검사가 형식만 남는 상태
  - 툴박스에 적힌 스크립트·템플릿이 실제로는 없는 상태(옮겨졌거나 지워짐)
  - 오류를 채팅에서만 고치고 매뉴얼에 남기지 않는 상태(실수 카탈로그의 수정 위치 강제)
  - 인터뷰가 끝나지 않았는데(미해결 질문 남음) "사람 없이 실행 가능"으로 표시되는 상태

한계(명시)
  - 매뉴얼 *내용*이 옳은지는 보지 않는다. 형식이 갖춰졌는지와 도구가 실재하는지만 본다.
  - read·human 항목은 실행하지 않는다. 에이전트가 증거를 보고해야 하며,
    이 스크립트는 그 목록만 낸다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MANUALS_DIR = REPO / "manuals"
TEMPLATE_DIR_NAME = "_template"

# 본문 필수 절 — 이 순서대로 있어야 한다
REQUIRED_SECTIONS = [
    "## 1. 목적과 범위",
    "## 2. 시작 전 입력",
    "## 3. 절차",
    "## 4. 판단 분기",
    "## 5. 금지",
    "## 6. 툴박스 사용 규칙",
    "## 7. 완료 조건 자체 검사",
    "## 8. 실수 카탈로그",
    "## 9. 변경 이력",
]
REQUIRED_KEYS = ["id", "title", "version", "updated", "readiness", "toolbox", "verify"]
READINESS = {"draft", "ready"}
VERIFY_HOW = {"cmd", "read", "human"}
# 실수 카탈로그의 '매뉴얼 수정 위치' 칸이 가리킬 수 있는 곳: 절(§3) · 완료 조건(V2) · 툴박스
FIX_LOCATION_RE = re.compile(r"(§[1-9]|\bV\d+\b|툴박스)")
ARG_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
SAFE_ARG_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
CMD_TIMEOUT_SEC = 300


@dataclass
class Manual:
    path: Path
    meta: dict
    body: str
    errors: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.parent.name


def _split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """'---' 로 감싼 YAML 머리말과 본문을 나눈다. 실패하면 (None, 원문, 사유)."""
    if not text.startswith("---\n"):
        return None, text, "머리말(---)로 시작하지 않는다"
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text, "머리말 닫는 '---' 가 없다"
    try:
        meta = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:  # 파싱 실패는 타입명과 함께 보고
        return None, text, f"머리말 YAML 파싱 실패({type(exc).__name__})"
    if not isinstance(meta, dict):
        return None, text, "머리말이 키-값 사전이 아니다"
    return meta, text[end + 5 :], None


def load_manual(path: Path) -> Manual:
    meta, body, err = _split_frontmatter(path.read_text(encoding="utf-8"))
    m = Manual(path=path, meta=meta or {}, body=body)
    if err:
        m.errors.append(err)
    return m


def _section_text(body: str, heading: str) -> str:
    """heading 부터 다음 '## ' 직전까지."""
    i = body.find(heading)
    if i == -1:
        return ""
    j = body.find("\n## ", i + len(heading))
    return body[i : j if j != -1 else len(body)]


def _table_rows(section: str) -> list[list[str]]:
    """마크다운 표의 데이터 행(머리줄·구분줄 제외)을 칸 목록으로."""
    rows = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")]
    out = []
    for ln in rows[2:]:  # 0 = 머리줄, 1 = 구분줄
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if any(cells):
            out.append(cells)
    return out


def check_manual(m: Manual, repo: Path = REPO) -> list[str]:
    """한 매뉴얼의 위반 목록. 빈 목록이면 통과."""
    errs = list(m.errors)
    if errs:  # 머리말이 깨졌으면 이후 검사는 의미 없음
        return errs
    meta = m.meta
    is_template = m.name == TEMPLATE_DIR_NAME

    # ── 머리말 키 ──
    for k in REQUIRED_KEYS:
        if k not in meta:
            errs.append(f"머리말 키 누락: {k}")
    if errs:
        return errs
    if not is_template and meta["id"] != m.name:
        errs.append(f"id '{meta['id']}' 가 폴더명 '{m.name}' 과 다르다")
    if not isinstance(meta["version"], int) or meta["version"] < 1:
        errs.append("version 은 1 이상의 정수여야 한다")
    if meta["readiness"] not in READINESS:
        errs.append(f"readiness 는 {sorted(READINESS)} 중 하나 (받음: {meta['readiness']!r})")
    ready = meta["readiness"] == "ready"
    open_q = meta.get("open_questions") or []
    if ready and open_q:
        errs.append(f"readiness=ready 인데 미해결 질문 {len(open_q)}건 — 인터뷰가 끝나지 않았다")

    # ── 툴박스: 적힌 경로가 저장소에 실재하는가 ──
    toolbox = meta["toolbox"] or []
    if ready and not toolbox:
        errs.append("readiness=ready 인데 툴박스가 비어 있다")
    for i, t in enumerate(toolbox):
        if not isinstance(t, dict) or not t.get("path") or not t.get("role"):
            errs.append(f"툴박스[{i}] 에 path·role 이 모두 있어야 한다")
            continue
        if not (repo / t["path"]).exists():
            errs.append(f"툴박스 경로가 저장소에 없다: {t['path']}")

    # ── 완료 조건: 항목마다 확인 방법이 있는가 ──
    verify = meta["verify"] or []
    if not verify:
        errs.append("완료 조건(verify)이 0건 — '완료'가 정의되지 않았다")
    seen: set[str] = set()
    for i, v in enumerate(verify):
        if not isinstance(v, dict):
            errs.append(f"verify[{i}] 가 사전이 아니다")
            continue
        vid = v.get("id", "")
        if not re.fullmatch(r"V\d+", str(vid)):
            errs.append(f"verify[{i}] id 는 V1·V2 형식 (받음: {vid!r})")
        elif vid in seen:
            errs.append(f"verify id 중복: {vid}")
        seen.add(str(vid))
        if not v.get("check"):
            errs.append(f"{vid}: check(무엇이 참이어야 하는가)가 비었다")
        how = v.get("how")
        if how not in VERIFY_HOW:
            errs.append(f"{vid}: how 는 {sorted(VERIFY_HOW)} 중 하나 (받음: {how!r})")
        elif how == "cmd" and not v.get("cmd"):
            errs.append(f"{vid}: how=cmd 인데 cmd 가 없다")
        elif how in ("read", "human") and not v.get("evidence"):
            errs.append(f"{vid}: how={how} 인데 evidence(무엇을 보고 판정하는가)가 없다")
    if ready and not any(isinstance(v, dict) and v.get("how") == "cmd" for v in verify):
        errs.append("readiness=ready 인데 기계 실행(cmd) 완료 조건이 0건")

    # ── 본문 절 순서 ──
    pos = -1
    for h in REQUIRED_SECTIONS:
        p = m.body.find(h)
        if p == -1:
            errs.append(f"본문 절 누락: '{h}'")
        elif p < pos:
            errs.append(f"본문 절 순서 어긋남: '{h}'")
        else:
            pos = p

    # ── 실수 카탈로그: 행마다 '매뉴얼 수정 위치'가 있는가 ──
    for row in _table_rows(_section_text(m.body, "## 8. 실수 카탈로그")):
        if len(row) < 4:
            errs.append(f"실수 카탈로그 행의 칸이 4개 미만: {row}")
            continue
        if not FIX_LOCATION_RE.search(row[3]):
            errs.append(
                f"실수 카탈로그 행 '{row[0]}' 의 수정 위치가 "
                "§N·VN·툴박스 중 어디도 가리키지 않는다 "
                "— 채팅이 아니라 매뉴얼을 고쳐야 한다"
            )

    # ── 변경 이력: 현재 버전 행이 있는가 ──
    if isinstance(meta["version"], int):
        hist = _section_text(m.body, "## 9. 변경 이력")
        if not re.search(rf"\|\s*v{meta['version']}\s*\|", hist):
            errs.append(f"변경 이력에 현재 버전 v{meta['version']} 행이 없다")
    return errs


def discover(manuals_dir: Path = MANUALS_DIR) -> list[Path]:
    return sorted(manuals_dir.glob("*/MANUAL.md"))


def cmd_lint(manuals_dir: Path = MANUALS_DIR, repo: Path = REPO) -> int:
    paths = discover(manuals_dir)
    real = [p for p in paths if p.parent.name != TEMPLATE_DIR_NAME]
    if not real:  # 스캔 0건은 통과가 아니라 실패
        print(f"❌ 매뉴얼 0건 — {manuals_dir} 아래 <id>/MANUAL.md 를 찾지 못했다")
        return 1
    bad = 0
    for p in paths:
        errs = check_manual(load_manual(p), repo)
        rel = p.relative_to(repo) if p.is_relative_to(repo) else p
        if errs:
            bad += 1
            print(f"❌ {rel}")
            for e in errs:
                print(f"   · {e}")
        else:
            print(f"✅ {rel}")
    print(f"매뉴얼 {len(paths)}건 (템플릿 포함) · 위반 {bad}건")
    return 1 if bad else 0


def cmd_list() -> int:
    for p in discover():
        m = load_manual(p)
        print(
            f"{m.name:32} v{m.meta.get('version', '?')}  {m.meta.get('readiness', '?'):6}  "
            f"{m.meta.get('title', '')}"
        )
    return 0


def _fill_args(cmd: str, args: dict[str, str]) -> tuple[str | None, list[str]]:
    missing = sorted({a for a in ARG_RE.findall(cmd) if a not in args})
    if missing:
        return None, missing
    return ARG_RE.sub(lambda mo: args[mo.group(1)], cmd), []


def cmd_verify(
    manual_id: str, raw_args: list[str], manuals_dir: Path = MANUALS_DIR, repo: Path = REPO
) -> int:
    path = manuals_dir / manual_id / "MANUAL.md"
    if not path.exists():
        print(f"❌ 매뉴얼 없음: {manual_id}")
        return 2
    args: dict[str, str] = {}
    for a in raw_args:
        k, sep, v = a.partition("=")
        if not sep or not SAFE_ARG_VALUE_RE.match(v):
            print(f"❌ --arg 형식 오류(k=v · 값은 영숫자와 _.:/- 만): {a!r}")
            return 1
        args[k] = v
    m = load_manual(path)
    if errs := check_manual(m, repo):
        print("❌ 매뉴얼 구조가 깨져 있어 검사를 실행하지 않는다 — 먼저 lint 를 통과시켜라")
        for e in errs:
            print(f"   · {e}")
        return 1
    failed = 0
    pending: list[dict] = []
    print(f"[완료 조건 자체 검사] {m.meta['title']} (v{m.meta['version']})")
    for v in m.meta["verify"]:
        if v["how"] != "cmd":
            pending.append(v)
            continue
        cmd, missing = _fill_args(v["cmd"], args)
        if cmd is None:
            failed += 1
            print(f"  ❌ {v['id']} 인자 누락: {', '.join('--arg ' + x + '=…' for x in missing)}")
            continue
        try:
            r = subprocess.run(
                ["bash", "-c", cmd],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CMD_TIMEOUT_SEC,
            )
            rc = r.returncode
            tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        except subprocess.TimeoutExpired:
            rc, tail = -1, [f"{CMD_TIMEOUT_SEC}초 타임아웃"]
        mark = "✅" if rc == 0 else "❌"
        failed += rc != 0
        print(f"  {mark} {v['id']} (exit {rc}) {v['check']}")
        if rc != 0:
            for ln in tail:
                print(f"       {ln}")
    for v in pending:
        print(f"  ⏳ {v['id']} [{v['how']}] {v['check']}\n       증거로 댈 것: {v['evidence']}")
    print(f"기계 검사 실패 {failed}건 · 에이전트 증거 필요 {len(pending)}건")
    if pending and not failed:
        print("→ 위 ⏳ 항목마다 증거를 보고서에 적은 뒤에만 '완료'라고 말한다")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("lint")
    sub.add_parser("list")
    pv = sub.add_parser("verify")
    pv.add_argument("manual_id")
    pv.add_argument("--arg", action="append", default=[], help="명령 자리 {name} 채우기 (name=값)")
    ns = ap.parse_args(argv)
    if ns.command == "lint":
        return cmd_lint()
    if ns.command == "list":
        return cmd_list()
    return cmd_verify(ns.manual_id, ns.arg)


if __name__ == "__main__":
    sys.exit(main())
