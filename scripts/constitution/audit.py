#!/usr/bin/env python3
"""scripts/constitution/audit.py — WhyMath 위헌 심사 (코딩 헌법 제10조).

원본: Kiki 헌법 v1.1 갱신 꾸러미(2026-09-26)의 audit.py. 이 저장소로 옮기며 적용한
로컬 패치는 `# whymath 패치(CONST-02):` 주석으로 표시했고 목록은 UPSTREAM.md에 있다.

무엇을 검사하나
  1) 원본 등록부 심사 : rules.yaml의 sources에 등록된 저장소 안 원본이 실제로 있는가 (제7조)
  2) 등록부 심사     : 현재 단계까지 도입된 L4·L5 규칙에 집행 장치가 있고, 연결되어 있는가
  3) 위반 심사       : 집행 장치를 실제로 실행해 통과하는가

사용법
  python scripts/constitution/audit.py                  # 전체 심사 (위반 시 종료 코드 1)
  python scripts/constitution/audit.py --hook           # Claude Code Stop 훅용 (위반 시 2)
  python scripts/constitution/audit.py --sources-only   # 원본 등록부만 검사 (규칙 R4-01)
  python scripts/constitution/audit.py --report out.md  # 완료 보고서에 붙일 표를 파일로 저장
  python scripts/constitution/audit.py --no-run         # 검사 실행 없이 등록 상태만 확인
  python scripts/constitution/audit.py --stage 3        # 단계 상향 미리보기 (STAGE 파일 불변)
  python scripts/constitution/audit.py --json out.json  # 기계가 읽는 결과 (래칫이 소비)

종료 코드
  0 = 문제 없음 / 1 = 위반 (일반) / 2 = 위반 (훅 모드) 또는 심사 불가(등록부 파손)

필요 패키지: pyyaml
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 윈도우 콘솔(cp949)에서 한글·기호가 깨져 스크립트가 죽지 않도록 UTF-8로 출력
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

try:
    import yaml
except ImportError:
    print("⛔ pyyaml이 없습니다. 설치: python -m pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]  # 저장소 최상위 (scripts/constitution/ 의 두 단계 위)
RULES_FILE = ROOT / "constitution" / "rules.yaml"
STAGE_FILE = ROOT / "constitution" / "STAGE"  # 현재 이식 단계 (숫자 한 개)
CHECK_TIMEOUT_SEC = 180  # 검사 하나당 최대 3분
LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

# whymath 패치(CONST-02): 외부 원본의 version 칸에 남은 자리표시자를 '표기 있음'으로 세지 않는다.
# 원본 코드는 bool(version)만 봐서 "고시 번호·판 확인 후 기입"이 ✅ 통과로 나왔다(실측).
VERSION_PLACEHOLDERS = ("확인 후 기입", "미확인", "TBD", "TODO", "기입 필요", "(미정)")


@dataclass
class Result:
    rule_id: str
    level: str
    status: str  # 통과 / 위반 / 경고 / 미연결 / 집행 장치 없음 / 예정 / 등록만
    detail: str = ""
    blocking: bool = False  # True면 종료 코드를 실패로 만듦


# ─────────────────────────── 읽기 ───────────────────────────
def read_text(path: Path) -> str:
    """파일이 없으면 빈 문자열. 없다는 사실은 호출한 쪽에서 판정한다."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def load_registry() -> dict:
    try:
        data = yaml.safe_load(read_text(RULES_FILE))  # safe_load: YAML 안의 임의 코드 실행 방지
    except yaml.YAMLError as e:
        fail_hard(f"rules.yaml 형식 오류: {type(e).__name__}: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        fail_hard(f"규칙 등록부를 찾을 수 없거나 'rules' 목록이 없음: {RULES_FILE}")
    ids = [r.get("id") for r in data["rules"] if isinstance(r, dict)]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        fail_hard(f"규칙 ID 중복: {sorted(dup)}")
    # v1.1 등록부 형식 검사: 항목이 엉뚱한 목록에 들어가도 YAML 문법 오류는 나지 않으므로
    # 직접 확인한다
    need = {"id", "article", "chapter", "axis", "statement", "level", "stage"}
    for r in data["rules"]:
        if not isinstance(r, dict) or not need <= set(r):
            rid = r.get("id", "?") if isinstance(r, dict) else r
            fail_hard(f"규칙 항목의 필수 필드 누락: {rid} (필요: {', '.join(sorted(need))})")
        if r["level"] not in LEVEL_ORDER:
            fail_hard(f"{r['id']}: 알 수 없는 강도 '{r['level']}' (L1~L5만 허용)")
    for s in data.get("sources") or []:
        looks_like_rule = isinstance(s, dict) and ("statement" in s or "level" in s)
        if not isinstance(s, dict) or looks_like_rule or not (s.get("path") or s.get("external")):
            name = (s.get("id") or s.get("name")) if isinstance(s, dict) else s
            fail_hard(
                f"원본 등록부(sources)에 규칙처럼 보이는 항목이 있음: {name} — 규칙을 파일 맨 끝에 "
                "붙여 넣으면 sources 목록으로 들어갑니다. rules: 목록 안(sources: 줄 위)에 넣거나 "
                "merge_rules.py를 쓰세요"
            )
    return data


def current_stage() -> int:
    """--stage 미리보기가 있으면 그 값, 없으면 constitution/STAGE 파일의 숫자(없으면 1)."""
    # whymath 패치(CONST-02): 단계 상향 전에 '올리면 무엇이 켜지나'를 STAGE 파일을 고치지 않고 본다.
    if ARGS.stage is not None:
        return ARGS.stage
    raw = read_text(STAGE_FILE).strip()
    try:
        return int(raw) if raw else 1
    except ValueError:
        fail_hard(f"STAGE 파일에는 숫자 하나만 있어야 함: '{raw}'")
        raise  # fail_hard가 종료하므로 도달하지 않는다(타입 검사용)


def fail_hard(msg: str) -> None:
    """등록부 자체가 망가진 경우: 심사를 진행할 수 없으므로 즉시 실패(종료 코드 2)."""
    print(f"⛔ 위헌 심사 불가 — {msg}", file=sys.stderr)
    # whymath 패치(CONST-02): 원본은 일반 모드에서 1로 끝나 '위반'과 '심사 불가'가 같은 코드였다.
    # 래칫(audit_ratchet.py)이 둘을 구분해야 하므로 심사 불가는 모드와 무관하게 2로 통일한다.
    sys.exit(2)


# ─────────────────────────── 심사 ───────────────────────────
def audit_sources(data: dict) -> list[Result]:
    """원본 등록부 심사 (제7조): 저장소 안 원본이 실제로 존재하는가."""
    results = []
    for s in data.get("sources", []) or []:
        name = s.get("name", "(이름 없음)")
        if s.get("external"):
            version = str(s.get("version") or "").strip()
            placeholder = any(p in version for p in VERSION_PLACEHOLDERS)
            ok = bool(version) and not placeholder
            if not version:
                detail = "외부 원본은 version(판·버전) 표기가 필수"
            elif placeholder:
                detail = f"version이 자리표시자임: '{version}' — 실제 판·버전을 기입"
            else:
                detail = ""
            results.append(Result(f"원본:{name}", "L5", "통과" if ok else "위반", detail, not ok))
            continue
        path = s.get("path", "")
        exists = bool(path) and (ROOT / path).exists()
        detail = "" if exists else f"등록된 원본이 없음: {path}"
        results.append(
            Result(f"원본:{name}", "L5", "통과" if exists else "위반", detail, not exists)
        )
    return results


def wiring_text() -> str:
    """pre-commit 설정과 GitHub Actions 워크플로 전체 텍스트 (연결 여부 판정용)."""
    parts = [read_text(ROOT / ".pre-commit-config.yaml")]
    wf = ROOT / ".github" / "workflows"
    if wf.is_dir():
        parts += [read_text(p) for p in sorted(wf.glob("*.y*ml"))]
    return "\n".join(parts)


def to_command(run: str) -> list[str] | str:
    """'python ...'은 지금 실행 중인 파이썬으로 바꿔 윈도우의 python/python3 차이를 없앤다."""
    if run.startswith("python "):
        return [sys.executable] + shlex.split(run[len("python ") :], posix=True)
    return run  # bash·pytest 등은 셸로 실행 (윈도우에서는 Git Bash 필요)


def run_check(rule: dict) -> tuple[bool, str]:
    cmd = to_command(rule["run"])
    try:
        res = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECK_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, f"{CHECK_TIMEOUT_SEC}초 시간 초과"
    except OSError as e:
        return False, f"실행 불가: {type(e).__name__}: {e}"
    out = (res.stdout.strip() + "\n" + res.stderr.strip()).strip()
    return res.returncode == 0, out[-400:]  # 메시지가 길면 끝부분만 (보통 요약이 끝에 있음)


def audit_rules(data: dict, stage: int, do_run: bool) -> list[Result]:
    wired = wiring_text()
    results = []
    for r in data["rules"]:
        rid, level = r.get("id", "?"), r.get("level", "L1")
        rule_stage = int(r.get("stage", 1))
        strong = LEVEL_ORDER.get(level, 1) >= 4

        if not strong:  # L1~L3은 문서 수준: 등록만 확인
            results.append(Result(rid, level, "등록만"))
            continue
        if rule_stage > stage:  # 아직 도입 단계가 아님
            results.append(Result(rid, level, "예정", f"{rule_stage}단계에서 도입"))
            continue

        check = r.get("check", "")
        if not check or not (ROOT / check).exists():  # 제10조 ①: 효력 없음
            need = f"필요: {check or '(미지정)'}"
            results.append(Result(rid, level, "집행 장치 없음", need, True))
            continue
        run = (r.get("run") or "").strip()
        # whymath 패치(CONST-02): run이 비면 원본은 배선 검사에서 `"" in 텍스트`가 항상 참이라
        # '연결됨'으로 보고, 실행도 건너뛰어 '통과'로 끝났다(주입 실측). L4·L5는 실행할 명령이
        # 없으면 집행 장치가 없는 것이다. R4-01은 원본 등록부 심사로 대체되므로 예외.
        if not run and rid != "R4-01":
            results.append(Result(rid, level, "집행 장치 없음", "run 미지정", True))
            continue
        if level == "L5" and stage >= 3 and run not in wired and check not in wired:
            results.append(
                Result(rid, level, "미연결", "pre-commit·CI 어디에도 등록되지 않음", True)
            )
            continue
        if not do_run:
            results.append(Result(rid, level, "통과", "실행 생략(--no-run)"))
            continue
        if rid == "R4-01":  # 자기 자신 재귀 실행 방지: 원본 심사는 이미 수행됨
            results.append(Result(rid, level, "통과", "원본 등록부 심사로 대체"))
            continue

        ok, out = run_check(r)
        if ok:
            results.append(Result(rid, level, "통과"))
        elif level == "L5":
            results.append(Result(rid, level, "위반", out, True))
        else:  # L4는 경고만, 실패로 만들지 않음
            results.append(Result(rid, level, "경고", out, False))
    return results


# ─────────────────────────── 출력 ───────────────────────────
ICON = {
    "통과": "✅",
    "위반": "⛔",
    "경고": "⚠️",
    "미연결": "🔌",
    "집행 장치 없음": "📭",
    "예정": "⏳",
    "등록만": "📄",
}


def render(results: list[Result], stage: int) -> str:
    blocking = [r for r in results if r.blocking]
    preview = f" (미리보기 --stage {stage})" if ARGS.stage is not None else ""
    lines = [
        f"## 위헌 심사 결과 (이식 {stage}단계){preview}",
        "",
        f"- 심사 항목 {len(results)}개 · 차단 사유 {len(blocking)}건",
        "",
        "| 항목 | 강도 | 상태 | 내용 |",
        "|---|---|---|---|",
    ]
    for r in results:
        detail = r.detail.replace("\n", " ").replace("|", "\\|")[:160]
        icon = ICON.get(r.status, "")
        lines.append(f"| {r.rule_id} | {r.level} | {icon} {r.status} | {detail} |")
    return "\n".join(lines)


def write_json(path: str, results: list[Result], stage: int) -> None:
    """whymath 패치(CONST-02): 래칫이 한국어 표를 긁지 않고 읽을 수 있게 결과를 JSON으로 낸다."""
    payload = {
        "stage": stage,
        "preview": ARGS.stage is not None,
        "total": len(results),
        "blocking": sum(1 for r in results if r.blocking),
        "results": [asdict(r) for r in results],
    }
    try:
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"⚠️ JSON 저장 실패: {type(e).__name__}: {e}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="WhyMath 위헌 심사")
    ap.add_argument(
        "--hook", action="store_true", help="Claude Code Stop 훅 모드 (위반 시 종료 코드 2)"
    )
    ap.add_argument("--sources-only", action="store_true", help="원본 등록부만 검사")
    ap.add_argument("--no-run", action="store_true", help="검사 실행 생략")
    ap.add_argument("--report", metavar="FILE", help="결과 표를 Markdown 파일로 저장")
    ap.add_argument("--json", metavar="FILE", help="결과를 JSON 파일로 저장 (whymath 패치)")
    ap.add_argument(
        "--stage",
        type=int,
        choices=range(1, 7),
        metavar="N",
        help="STAGE 파일 대신 이 단계로 심사 (미리보기 · whymath 패치)",
    )
    return ap.parse_args()


def main() -> int:
    if ARGS.hook and not sys.stdin.isatty():
        # Stop 훅 무한 반복 방지: 이미 훅 때문에 작업을 이어가는 중이면 이번엔 통과시킴
        try:
            # 훅 입력은 UTF-8 JSON — 로캘(cp949) 해독을 피해 바이트로 읽는다
            if json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace")).get(
                "stop_hook_active"
            ):
                return 0
        except (json.JSONDecodeError, ValueError):
            pass

    data = load_registry()
    stage = current_stage()
    results = audit_sources(data)
    if not ARGS.sources_only:
        results += audit_rules(data, stage, do_run=not ARGS.no_run)

    table = render(results, stage)
    if ARGS.report:
        try:
            Path(ARGS.report).write_text(table + "\n", encoding="utf-8")
        except OSError as e:
            print(f"⚠️ 보고서 저장 실패: {type(e).__name__}: {e}", file=sys.stderr)
    if ARGS.json:
        write_json(ARGS.json, results, stage)

    blocking = [r for r in results if r.blocking]
    # 훅 모드에서는 stderr가 AI에게 전달되므로, 표 전체와 함께 해야 할 일을 명확히 적는다
    stream = sys.stderr if (ARGS.hook and blocking) else sys.stdout
    print(table, file=stream)
    if blocking and ARGS.hook:
        print(
            "\n헌법 제10조: 위 차단 사유를 해결하거나, 해결할 수 없으면 작업을 멈추고 사람에게 "
            "보고하세요. constitution/ 파일은 수정할 수 없습니다(제9조).",
            file=sys.stderr,
        )
    if not blocking:
        return 0
    return 2 if ARGS.hook else 1


if __name__ == "__main__":
    ARGS = parse_args()
    sys.exit(main())
