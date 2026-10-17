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
import ast
import json
import posixpath
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
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
CHECK_TIMEOUT_SEC = 180  # 규칙이 timeout_sec 를 주지 않았을 때의 기본값: 검사 하나당 3분
MAX_TIMEOUT_SEC = 1800  # 규칙이 늘릴 수 있는 상한(30분) — 무한 대기를 허용하지 않는다
LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

# whymath 패치(CONST-03): 규칙이 선택적으로 주는 실행 설정 3종(rules.yaml 필드).
#   timeout_sec : 1~MAX_TIMEOUT_SEC 정수 · cwd : 저장소 안 상대 디렉터리
#   shell       : true 일 때만 셸 문자열로 실행
# 셸 연산자(&& | ; > < ` $()가 든 run 은 shell: true 가 없으면 실행하지 않는다 — 문자열 실행을
# 기본값으로 두면 윈도우에서 실행기 결합이 보장되지 않고, 규칙 파일이 곧 임의 셸 스크립트가 된다.
SHELL_OPERATORS = re.compile(r"&&|\|\||[|;<>`]|\$\(")

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


def validate_exec_fields(rule: dict) -> None:
    """whymath 패치(CONST-03): 선택 실행 설정의 형식 검사. 틀리면 심사 불가(exit 2).

    형식이 틀린 설정을 조용히 기본값으로 바꾸면 '규칙이 요구한 격리를 못 받은 채' 실행된다.
    """
    rid = rule.get("id", "?")
    timeout = rule.get("timeout_sec")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= MAX_TIMEOUT_SEC
    ):
        fail_hard(f"{rid}: timeout_sec 는 1~{MAX_TIMEOUT_SEC} 정수여야 함: {timeout!r}")
    cwd = rule.get("cwd")
    if cwd is not None:
        text = cwd if isinstance(cwd, str) else ""
        parts = text.replace("\\", "/").split("/")
        if not text.strip() or text.startswith(("/", "\\")) or ":" in text or ".." in parts:
            fail_hard(f"{rid}: cwd 는 저장소 안 상대 디렉터리여야 함(절대경로·.. 금지): {cwd!r}")
    shell = rule.get("shell")
    if shell is not None and not isinstance(shell, bool):
        fail_hard(f"{rid}: shell 은 true/false 여야 함: {shell!r}")


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
        validate_exec_fields(r)
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


# ─────────────── 연결 판정 (whymath 패치 CONST-03 · 제10조 ①) ───────────────
# 원본은 pre-commit·워크플로 파일 **전체 텍스트**에 run 문자열이 부분 문자열로 들어 있으면 '연결'로
# 셌다. 그러면 ① 주석 속 문자열·무관한 echo 가 연결로 셈 ② 파일 하나만 도는 pytest run 35건은 CI 가
# 디렉터리 단위로 도는 순간 구조적으로 미연결이 되고 ③ 판정이 전역 STAGE 에 걸려 규칙 자신의 단계와
# 어긋났다. 아래는 워크플로를 **YAML 로 읽어 잡 스텝의 run 명령 단위**로 대조한다.
#
# 한계(정직 고지): 정적 판정이다. 스텝의 `if:` 조건·잡의 `needs`/경로 필터로 실제로는 안 도는
# 경우, 셸 변수·`$(...)` 치환, 파이썬 스크립트가 내부에서 다른 도구를 부르는 경우는 보지 못한다.
# 보지 못한 것은 '연결'로 세지 않는다(모른다 ≠ 아니다).
_CONTROL_WORDS = frozenset({"if", "then", "elif", "else", "do", "while", "until", "!", "{", "}"})
_SEGMENT_BREAKS = frozenset({"&&", "||", ";", "|", "|&", "&"})
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_ENV_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

# pytest 옵션 중 값을 따로 받는 것 — 값을 경로(위치 인자)로 오인하지 않기 위한 목록
_PYTEST_VALUE_OPTS = frozenset(
    {
        "--ignore", "--ignore-glob", "--deselect", "--cov-report", "--cov-fail-under",
        "--cov-config", "--maxfail", "--rootdir", "--dist", "--junitxml", "--tb", "--basetemp",
        "--import-mode", "--durations", "--timeout", "--randomly-seed", "--confcutdir",
    }
)  # fmt: skip
_PYTEST_SHORT_VALUE_OPTS = frozenset({"-k", "-m", "-c", "-p", "-n", "-o", "-W"})


@dataclass(frozen=True)
class CiCommand:
    """워크플로·pre-commit 이 실제로 실행하는 명령 하나."""

    source: str  # 어디서 왔나(파일:잡:스텝 이름) — 판정 근거를 사람이 되짚을 수 있게
    tokens: tuple[str, ...]  # 실행기 표기를 정규화한 토큰
    workdir: str  # 저장소 루트 기준 작업 디렉터리(posix, 루트면 "")


@dataclass
class WiringIndex:
    commands: list[CiCommand] = field(default_factory=list)
    hook_ids: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)  # 읽지 못한 파일·줄(조용히 삼키지 않는다)


def join_path(base: str, rel: str) -> str:
    """저장소 루트 기준 posix 경로 합성(`..` 정리). 루트 밖으로 나가면 그대로 `..` 로 남긴다."""
    joined = posixpath.normpath(posixpath.join(base or ".", rel))
    return "" if joined == "." else joined


def normalize_tokens(tokens: list[str]) -> list[str]:
    """실행기 표기 차이를 지운다: python3·python3.12·py → python, `python -m pytest` → pytest."""
    toks = list(tokens)
    while toks and _ENV_ASSIGN.match(toks[0]):
        toks.pop(0)  # FOO=1 python ... 의 환경변수 접두
    if not toks:
        return []
    if re.fullmatch(r"python(3(\.\d+)?)?|py", toks[0]):
        toks[0] = "python"
        if len(toks) >= 3 and toks[1] == "-m" and toks[2] == "pytest":
            toks = ["pytest"] + toks[3:]
    return [t[2:] if t.startswith("./") and len(t) > 2 else t for t in toks]


def _split_line(line: str) -> list[str]:
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    return list(lex)


def parse_script(script: str, base_workdir: str) -> tuple[list[tuple[str, list[str]]], int]:
    """`run:` 블록 하나를 (작업 디렉터리, 정규화 토큰) 목록으로 쪼갠다. 읽지 못한 줄 수도 돌려준다.

    주석·빈 줄·heredoc 본문은 명령이 아니므로 버린다. `a && b ; c | d` 는 명령 셋·넷으로 나누고
    `cd X` 는 이후 명령의 작업 디렉터리를 바꾼다. `\\` 줄잇기는 한 줄로 합친다.
    """
    commands: list[tuple[str, list[str]]] = []
    unparsed = 0
    cwd = base_workdir
    heredoc_end: str | None = None
    for raw in script.replace("\\\r\n", " ").replace("\\\n", " ").splitlines():
        if heredoc_end is not None:
            if raw.strip() == heredoc_end:
                heredoc_end = None
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        marker = _HEREDOC.search(line)
        try:
            tokens = _split_line(line)
        except ValueError:
            unparsed += 1  # 닫히지 않은 따옴표 등 — 추측하지 않고 센다
            continue
        if marker:
            heredoc_end = marker.group(1)
        segment: list[str] = []
        for tok in tokens + [";"]:
            if tok not in _SEGMENT_BREAKS:
                if tok not in ("(", ")"):
                    segment.append(tok)
                continue
            seg = segment
            segment = []
            while seg and seg[0] in _CONTROL_WORDS:
                seg = seg[1:]
            if not seg:
                continue
            if seg[0] == "cd" and len(seg) > 1:
                cwd = join_path(cwd, seg[1])
                continue
            norm = normalize_tokens(seg)
            if norm:
                commands.append((cwd, norm))
    return commands, unparsed


def _workdir(value: object) -> str:
    return join_path("", value) if isinstance(value, str) and value.strip() else ""


def build_wiring_index() -> WiringIndex:
    """워크플로(YAML)와 .pre-commit-config.yaml 에서 '실제로 실행되는 명령'을 모은다."""
    index = WiringIndex()
    wf_dir = ROOT / ".github" / "workflows"
    for path in sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []:
        try:
            doc = yaml.safe_load(read_text(path))
        except yaml.YAMLError as e:
            index.problems.append(f"{path.name} 읽기 실패({type(e).__name__})")
            continue
        if not isinstance(doc, dict):
            continue
        wf_wd = ((doc.get("defaults") or {}).get("run") or {}).get("working-directory")
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                    continue
                wd = _workdir(step.get("working-directory") or job_wd or wf_wd)
                label = f"{path.name}:{job_id}:{step.get('name') or '(이름 없음)'}"
                cmds, unparsed = parse_script(step["run"], wd)
                if unparsed:
                    index.problems.append(f"{label} 에서 {unparsed}줄을 읽지 못함")
                index.commands += [CiCommand(label, tuple(t), w) for w, t in cmds]
    pre_commit = ROOT / ".pre-commit-config.yaml"
    if pre_commit.is_file():
        try:
            conf = yaml.safe_load(read_text(pre_commit))
        except yaml.YAMLError as e:
            index.problems.append(f".pre-commit-config.yaml 읽기 실패({type(e).__name__})")
            conf = None
        repos = conf.get("repos") if isinstance(conf, dict) else None
        for repo in repos or []:
            for hook in (repo or {}).get("hooks") or []:
                if isinstance(hook, dict) and hook.get("id"):
                    index.hook_ids.add(str(hook["id"]))
    return index


@dataclass
class PytestSpec:
    paths: list[str] = field(default_factory=list)  # 저장소 루트 기준 대상 경로
    ignores: list[str] = field(default_factory=list)
    filtered: bool = False  # -k·-m·--deselect·--ignore-glob: 일부만 도는지 정적으로 알 수 없다


def parse_pytest(args: list[str], workdir: str) -> PytestSpec:
    spec = PytestSpec()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name == "--cov":
                # 값이 선택인 옵션: --cov=pkg 는 값, 맨 --cov 는 다음 토큰이 옵션이 아닐 때만 값
                i += 1 if eq or i + 1 >= len(args) or args[i + 1].startswith("-") else 2
                continue
            if name in _PYTEST_VALUE_OPTS:
                if not eq:
                    value = args[i + 1] if i + 1 < len(args) else ""
                if name == "--ignore" and value:
                    spec.ignores.append(join_path(workdir, value))
                if name in ("--deselect", "--ignore-glob"):
                    spec.filtered = True
                i += 1 if eq else 2
                continue
            i += 1
            continue
        if arg.startswith("-") and arg != "-":
            if arg[:2] in ("-k", "-m"):
                spec.filtered = True
            i += 1 if arg[:2] not in _PYTEST_SHORT_VALUE_OPTS or len(arg) > 2 else 2
            continue
        node = arg.split("::")
        if len(node) > 1:
            spec.filtered = True  # 노드 ID(file.py::test_x)는 파일의 일부 테스트만 지정한다
        spec.paths.append(join_path(workdir, node[0]))
        i += 1
    return spec


def _under(target: str, base: str) -> bool:
    base = base.rstrip("/")
    return target == base or target.startswith(base + "/")


def pytest_coverage(rule_spec: PytestSpec, index: WiringIndex) -> tuple[bool, str]:
    """규칙의 pytest 대상 경로 전부를 CI 의 pytest 스텝이 실제로 돌리는가.

    파일 하나를 지정한 규칙도, CI 가 그 파일을 품은 디렉터리를 필터 없이 돌면 연결이다.
    반대로 CI 스텝이 -k·-m·--deselect 로 걸러 내거나 --ignore 로 그 경로를 빼면 연결이 아니다
    (필터는 일부만 돈다는 뜻이고, 무엇이 걸러지는지는 정적으로 알 수 없으므로 '연결'로 세지 않는다).
    """
    hits: list[str] = []
    for target in rule_spec.paths:
        found = None
        why = "CI 에 이 경로를 필터 없이 도는 pytest 스텝이 없음"
        for cmd in index.commands:
            if not cmd.tokens or cmd.tokens[0] != "pytest":
                continue
            ci = parse_pytest(list(cmd.tokens[1:]), cmd.workdir)
            if not any(_under(target, p) for p in ci.paths):
                continue
            if ci.filtered:
                why = (
                    f"{cmd.source} 가 -k/-m/--deselect 로 일부만 실행 — 이 경로가 도는지 알 수 없음"
                )
                continue
            if any(_under(target, ig) for ig in ci.ignores):
                why = f"{cmd.source} 가 --ignore 로 이 경로를 제외"
                continue
            found = cmd.source
            break
        if found is None:
            return False, f"{target}: {why}"
        hits.append(found)
    return True, f"pytest 스텝이 대상 {len(hits)}곳을 실행: {hits[0]}"


def wrapper_references(script: Path, target_rel: str) -> bool:
    """`script` 가 subprocess 를 쓰며 값(대입·호출 인자)으로 target 경로·파일명을 담고 있는가.

    docstring·주석은 AST 의 값이 아니므로 세지 않는다 — 설명 문구로 연결을 꾸미지 못하게 한다.
    정적 근사다: 호출 인자까지 증명하지는 않는다.
    """
    try:
        tree = ast.parse(read_text(script))
    except SyntaxError:
        return False
    uses_subprocess = any(
        (isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module == "subprocess")
        for n in ast.walk(tree)
    )
    if not uses_subprocess:
        return False
    base = posixpath.basename(target_rel)
    for node in ast.walk(tree):
        values: list[ast.AST] = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            values.append(node.value)
        elif isinstance(node, ast.Call):
            values += list(node.args) + [k.value for k in node.keywords]
        for value in values:
            for const in ast.walk(value):
                if isinstance(const, ast.Constant) and isinstance(const.value, str):
                    text = const.value.replace("\\", "/")
                    if text == base or text == target_rel or text.endswith("/" + base):
                        return True
    return False


def ci_reaches_script(script_rel: str, index: WiringIndex) -> tuple[bool, str]:
    """CI 명령이 이 스크립트를 직접 실행하거나, 한 단계 래퍼(예: 래칫)가 서브프로세스로 부르는가."""
    for cmd in index.commands:
        if len(cmd.tokens) < 2 or cmd.tokens[0] != "python":
            continue
        script = join_path(cmd.workdir, cmd.tokens[1])
        if script == script_rel:
            return True, f"CI 스텝이 직접 실행: {cmd.source}"
        wrapper = ROOT / script
        if wrapper.is_file() and wrapper_references(wrapper, script_rel):
            return (
                True,
                f"간접 연결(정적 근사): {cmd.source} 가 {script} 를 실행하고 "
                f"그것이 {script_rel} 을 부름",
            )
    return False, f"CI 어디에도 {script_rel} 을 실행하는 스텝이 없음"


def _part_wired(wd: str, toks: list[str], index: WiringIndex) -> tuple[bool, str]:
    """명령 하나(작업 디렉터리 wd)가 CI·pre-commit 에서 실행되는가."""
    # 같은 작업 디렉터리에서 같은 명령으로 시작하면 연결(CI 가 인자를 더 붙여도 된다)
    for cmd in index.commands:
        if cmd.workdir == wd and list(cmd.tokens[: len(toks)]) == toks:
            return True, f"CI 스텝 연결: {cmd.source}"
    if toks[:2] == ["pre-commit", "run"] and len(toks) > 2 and toks[2] in index.hook_ids:
        return True, f"pre-commit 훅 등록: {toks[2]}"
    command = " ".join(toks)
    reason = f"CI·pre-commit 어디에도 이 명령({command})을 실행하는 스텝이 없음"
    if toks and toks[0] == "pytest":
        spec = parse_pytest(toks[1:], wd)
        if spec.paths:
            ok, detail = pytest_coverage(spec, index)
            if ok:
                return True, detail
            reason = f"pytest 대상이 CI 에서 실행되지 않음 — {detail}"
    if index.problems:
        reason += f" (읽지 못한 곳: {'; '.join(index.problems[:3])})"
    return False, reason


def judge_wiring(rule: dict, index: WiringIndex) -> tuple[bool, str]:
    """이 규칙의 검사가 CI·pre-commit 에서 실제로 실행되도록 연결돼 있는가(제10조 ①)."""
    rid, run = rule.get("id", "?"), (rule.get("run") or "").strip()
    if not index.commands and not index.hook_ids:
        note = " · ".join(index.problems)
        return (
            False,
            "워크플로·pre-commit 에서 명령을 하나도 읽지 못함(스캔 0건은 통과가 아니다)"
            + (f" — {note}" if note else ""),
        )
    if rid == "R4-01":
        # R4-01 의 run 은 audit.py 자신의 원본 등록부 심사로 대체된다(아래 실행 단계). 그 심사는
        # audit.py 전체 실행에 들어 있으므로, CI 가 audit.py 를 (래칫을 통해서라도) 돌리면 연결이다.
        return ci_reaches_script(rule["check"], index)
    cwd = (rule.get("cwd") or "").strip()
    rule_wd = join_path("", cwd) if cwd else ""
    try:
        parts, unparsed = parse_script(run, rule_wd)
    except ValueError as e:  # 방어: parse_script 는 줄 단위로 삼키지만 예외 타입은 남긴다
        return False, f"run 을 해석할 수 없음({type(e).__name__}): {run}"
    if unparsed or not parts:
        return False, f"run 을 해석할 수 없음(따옴표 오류 등): {run}"
    notes = []
    for wd, toks in parts:  # `a && b` 처럼 명령이 여럿이면 하나라도 연결이 아니면 연결이 아니다
        ok, why = _part_wired(wd, toks, index)
        if not ok:
            return False, why
        notes.append(why)
    return True, notes[0] if len(notes) == 1 else f"명령 {len(notes)}개 모두 연결: {notes[0]} 외"


# ─────────────── 실행 (whymath 패치 CONST-03 · 규칙별 실행 설정) ───────────────
def to_command(run: str, shell: bool) -> list[str] | str | None:
    """run 을 실행 가능한 형태로. python/python3/pytest 실행기 차이를 지금 파이썬으로 고정한다.

    셸 연산자가 있는데 shell: true 가 없으면 None(실행 거부). 셸을 거치지 않으니 인자가
    셸에 재해석되지 않는다.
    """
    if shell:
        return run
    if SHELL_OPERATORS.search(run):
        return None
    tokens = shlex.split(run, posix=True)
    if not tokens:
        return None
    if re.fullmatch(r"python(3(\.\d+)?)?", tokens[0]):
        return [sys.executable] + tokens[1:]
    if tokens[0] == "pytest":
        return [sys.executable, "-m", "pytest"] + tokens[1:]
    return tokens


def run_check(rule: dict) -> tuple[bool, str]:
    timeout = int(rule.get("timeout_sec") or CHECK_TIMEOUT_SEC)
    cwd_rel = (rule.get("cwd") or "").strip()
    cwd = (ROOT / cwd_rel).resolve() if cwd_rel else ROOT
    # load_registry 가 형식을 이미 검사했지만 심볼릭 링크로 저장소 밖을 가리킬 수 있어
    # 실행 직전에 한 번 더 본다
    if not cwd.is_relative_to(ROOT):
        return False, f"cwd 가 저장소 밖을 가리킴: {cwd_rel}"
    if not cwd.is_dir():
        return False, f"cwd 디렉터리가 없음: {cwd_rel}"
    try:
        cmd = to_command(rule["run"], bool(rule.get("shell")))
    except ValueError as e:
        return False, f"run 을 해석할 수 없음({type(e).__name__}): {e}"
    if cmd is None:
        return False, "run 에 셸 연산자가 있는데 shell: true 가 없어 실행하지 않음"
    try:
        res = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"{timeout}초 시간 초과"
    except OSError as e:
        return False, f"실행 불가: {type(e).__name__}: {e}"
    out = (res.stdout.strip() + "\n" + res.stderr.strip()).strip()
    return res.returncode == 0, out[-400:]  # 메시지가 길면 끝부분만 (보통 요약이 끝에 있음)


def audit_rules(data: dict, stage: int, do_run: bool) -> list[Result]:
    index = build_wiring_index()
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
        # whymath 패치(CONST-03): 연결 판정은 전역 STAGE 가 아니라 **규칙 자신의 단계**부터
        # (도입된 규칙은 그 순간부터 연결돼야 한다), L5 만이 아니라 L4 도 같게(제10조 ① 은
        # L4·L5 둘 다 '연결'을 요구한다 — 강도 차이는 위반 시 차단(L5)/경고(L4)에만 둔다).
        wired, how = judge_wiring(r, index)
        if not wired:
            results.append(Result(rid, level, "미연결", how, True))
            continue
        if not do_run:
            results.append(Result(rid, level, "통과", f"실행 생략(--no-run) · {how}"))
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
