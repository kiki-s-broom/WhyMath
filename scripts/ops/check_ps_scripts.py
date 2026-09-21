#!/usr/bin/env python3
"""PowerShell 스크립트 정적 검사 — 실행 검증이 불가능한 환경(Linux CI·샌드박스)용 최소 안전망.

이 저장소의 PS 스크립트는 Kiki 머신(Windows)에서만 실행된다. 즉 CI도 개발 세션도
`pwsh -NoProfile -Command { }` 같은 실행 검증을 할 수 없다. 그 공백에서 반복 발생한
결함을 기계로 고정한다.

검사 3종 (전부 실측 사고에서 유래):
  ① BOM 부재 — PS 5.1은 BOM 없는 UTF-8을 로케일(cp949)로 읽어 한국어 주석이 깨진다.
  ② 괄호 불균형 — 문자열·주석을 인식하는 파서로 (), {}, [] 짝을 본다.
  ③ 정의보다 먼저 호출되는 스크립트 지역 함수 — PowerShell은 위에서 아래로 실행하므로
     정의 아래에서만 호출할 수 있다.
     (사고 경위: 2026-08-22 bench_ollama.ps1이 Get-CommitFreeGB를 정의 79줄 위에서 호출해
      CommandNotFoundException으로 측정 1회가 공전했다.)

런북 검사 (OPS-57) — `docs/**/*.md`의 ```powershell 코드펜스도 같은 대상이다.
Kiki에게 건네는 PowerShell의 대부분은 .ps1이 아니라 **런북 코드펜스**인데 그쪽이
통째로 미검사였다. 붙여넣어 실행되는 순간 .ps1과 위험이 같다.

런북 전용 규칙 3종 (2026-09-01 관여도 트리아지 게이트 clear 사고에서 유래):
  ④ 보호 브랜치 직접 push — `git push origin main`은 `GH013: Changes must be made
     through a pull request`로 거부된다. 절차의 마지막 단계가 항상 실패한다.
  ⑤ `git reset --hard` 앞의 청결 확인 부재 — `git status --porcelain`으로 작업 트리가
     빈 것을 먼저 보지 않으면 미커밋 작업분을 무증상으로 지운다(2026-08-10 유형).
  ⑥ python 출력의 파이프·리다이렉트 — 한국어 Windows에서 stdout이 콘솔이 아니면
     로케일(cp949)로 인코딩돼 `UnicodeEncodeError`로 죽는다. 문서 앞부분에 UTF-8
     강제(PYTHONUTF8·PYTHONIOENCODING·Console::OutputEncoding)가 있어야 한다.

런북 전용 규칙 3종 추가 (OPS-60 — 2026-08-31 LIC-02 siyavula URL 프로브에서 유래):
  ⑦ 자동/예약 변수 대입 — `$home`·`$host`·`$input`·`$error`·`$args`·`$pwd`·`$matches`·
     `$profile`은 PowerShell이 미리 의미를 정해 둔 변수다. 대입은 거부되지만(오류가
     stderr로만 흘러 조용히 넘어가기 쉽다) **원래 값이 이미 참(truthy)이라** 그 뒤
     `if ($home)` 같은 조건은 대입 성공 여부와 무관하게 참이 돼, "대입 실패"가
     "성공"처럼 보이는 신호를 낸다.
  ⑧ `Invoke-WebRequest`(별칭 `iwr`)에 `-UseBasicParsing` 누락 — PowerShell 5.1(Windows
     기본 탑재판)은 이 스위치가 없으면 내부적으로 IE 엔진 파싱을 시도하다가 "Internet
     Explorer 엔진이 처음 사용되기 전에 최초 실행을 완료해야 합니다" 대화상자로
     **대화형 정지**한다 — 무인 실행(스케줄러·자동화)이 거기서 영원히 멈춘다.
  ⑨ `catch` 안에서 `$_.Exception.Response`를 존재 확인 없이 프로퍼티 체인으로 참조 —
     HTTP 계층 오류(4xx/5xx)에서는 `Response`가 채워지지만, **전송 계층** 오류
     (DNS 실패·TLS 실패·연결 거부·타임아웃)에서는 `Response` 자체가 `$null`이라
     `.StatusCode` 등 접근이 `NullReferenceException`으로 죽어 **원래 원인**(DNS·TLS·
     연결거부)이 화면에서 사라지고 무관한 오류만 남는다.

④번째 후보(if/else 다중행 구조)는 **범위를 좁혀 채택**했다 — 아래 "if/else 펜스 분리"
참조. 전면 채택(펜스 경계와 무관하게 모든 if/else 짝을 정적으로 추적)은 중첩·backtick
줄바꿈·문자열 안의 `else` 같은 경우의 수가 많아 오탐 위험이 크다고 판단해 보류했다.
대신 **펜스가 `else`/`elseif`로 시작하는 경우만** 잡는다 — 이 형태는 그 펜스 안에
대응하는 `if`가 있을 수 없으므로(있다면 `else`로 시작하지 않는다) 예외 없이 항상
구조적으로 깨져 있다(오탐 0, 위양성 0인 좁은 부분집합).

런북 전용 규칙 3종 추가 (OPS-73 — 2026-08-31 HARN-38·2026-09-10 OPS-72 "실행용 코드펜스에
증거 혼입" 사고 2회차에서 유래. 1회차 대책은 CLAUDE.md 산문 규칙이었는데 재량이 남아
2회차가 났다 — 이번엔 코드로 집행한다):
  ⑩ 셀 프롬프트 접두 — 줄 시작이 `$ `·`PS>`·`PS C:\\...>` — 실행 예시·터미널 캡처를
     그대로 실행용 펜스에 붙였을 가능성. 붙여넣으면 프롬프트 문자열 자체가 인자로
     파싱된다.
  ⑪ 화살표(`→`·`←`) 뒤에 한국어 판정어(`존재`·`성공`·`실패`... ) — 실행 결과·증거를
     그대로 인용한 줄. `git cat-file -e <경로>  → 존재`가 실측 사고 그 자체다 — 화살표
     뒤 텍스트가 앞 명령의 **추가 인자**로 파싱된다.
  ⑫ 커밋 해시+메시지 형태의 줄(짧은 hex 토큰으로 시작하는 줄) — `b64f470d  OPS-72: ... (#1065)`
     같은 줄이 실측 사고다. 메시지 끝의 `(#1234)`가 PowerShell에서 식으로 파싱돼
     ParserError가 난다.
  대상: `docs/**/*.md` + `.claude/commands/*.md`의 powershell 펜스(기존 ⑦~⑨와 동일
  경로 — 신규 도구가 아니라 규칙 추가).

**판정 범위 (과신 금지)**: ④~⑫는 "런북이 주의를 지시하는가"를 **문서 순서**로 본다 —
위험 명령보다 앞에 선행 스텝이 있는지만 확인한다. 특정 붙여넣기가 실제로 안전한지,
사람이 그 스텝을 실제로 실행했는지는 판정하지 않는다. 그리고 **의미적 결함**
(예: 변별력 없는 검증 스텝을 차단 지점으로 오인)은 정적 검사로 잡히지 않는다. ⑧은
한 코드 줄 안에서만 `-UseBasicParsing`을 찾는다 — 백틱 줄바꿈으로 인자가 다음 줄에
이어지면 놓친다(좁히는 쪽 선택 — 오탐보다 미탐이 안전하다는 이 파일의 기존 원칙과 동일).

**⑩~⑫의 핵심 한계(과신 금지 — OPS-73 acceptance④)**: 2026-09-10 OPS-72 사고의 실제
실패 표면은 세션이 *채팅으로* 낸 증거 블록이었다 — CI는 채팅도 PR 본문도 보지
않는다. 이 가드가 덮는 것은 **저장소에 커밋된** 런북·커맨드 문서뿐이다.

| 표면 | ⑩~⑫가 잡는가 |
|---|---|
| `docs/**/*.md`에 커밋된 코드펜스 | 잡음(이 가드의 대상) |
| `.claude/commands/*.md`에 커밋된 코드펜스 | 잡음(이 가드의 대상) |
| PR 본문(마크다운 텍스트, 커밋되지 않음) | 못 잡음 — CI가 PR 본문을 스캔하지
  않는다(2026-09-10 PR #1093 본문 실례) |
| 세션이 채팅으로 내는 증거 블록 | 못 잡음 — 이 사고의 실제 발단. 유일한 방어선은 CLAUDE.md
  「실행용 블록과 증거 블록의 분리」 규칙이며, 그 규칙은 이미 2회 실패했다(2026-08-31·
  2026-09-10) |
| `docs/reviews/**` 등 사후 커밋되는 리뷰 문서 | 잡음(`docs/**/*.md`에 포함) — 다만
  PR 본문에서 그대로 복사해 커밋되는 경로만 방어되고, 커밋되지 않은 리뷰 코멘트는 못 잡음 |

사용:  python3 scripts/ops/check_ps_scripts.py [경로...]
       인자 없으면 scripts/**/*.ps1 + docs/**/*.md + .claude/commands/*.md 코드펜스 전부
종료:  0 통과 / 1 위반
"""

from __future__ import annotations

import pathlib
import re
import sys

PAIRS = {"(": ")", "{": "}", "[": "]"}


def strip_noncode(src: str) -> str:
    """주석·문자열을 공백으로 치환한다. 줄 번호와 길이는 보존한다."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if src.startswith("<#", i):  # 블록 주석
            j = src.find("#>", i)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c == "#":  # 줄 주석
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif c == "'":  # 작은따옴표 문자열
            j = i + 1
            while j < n:
                if src[j] == "'":
                    if j + 1 < n and src[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
        elif c == '"':  # 큰따옴표 문자열
            j = i + 1
            while j < n:
                if src[j] == "`":
                    j += 2
                    continue
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
        elif c == "`":  # 이스케이프
            i += 2
        else:
            i += 1
    return "".join(out)


def check_balance(code: str) -> list[str]:
    stack: list[tuple[str, int]] = []
    issues: list[str] = []
    line = 1
    for ch in code:
        if ch == "\n":
            line += 1
        elif ch in PAIRS:
            stack.append((ch, line))
        elif ch in ")}]":
            if not stack:
                issues.append(f"L{line}: 짝 없는 닫는 괄호 {ch!r}")
            else:
                op, ol = stack.pop()
                if PAIRS[op] != ch:
                    issues.append(f"L{line}: {op!r}(L{ol})와 {ch!r}가 짝이 맞지 않음")
    issues += [f"L{ol}: 닫히지 않은 {op!r}" for op, ol in stack]
    return issues


def check_call_before_def(code: str) -> list[str]:
    lines = code.split("\n")
    defs: dict[str, int] = {}
    for idx, ln in enumerate(lines, start=1):
        m = re.match(r"\s*function\s+([A-Za-z][\w-]*)", ln)
        if m:
            defs.setdefault(m.group(1), idx)

    issues: list[str] = []
    for name, def_line in defs.items():
        pat = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
        for idx, ln in enumerate(lines, start=1):
            if idx >= def_line or not pat.search(ln):
                continue
            if re.match(r"\s*function\s", ln):  # 다른 함수 정의 줄은 제외
                continue
            issues.append(
                f"L{idx}: {name}() 를 정의(L{def_line})보다 먼저 호출한다 "
                "— PowerShell은 위에서 아래로 실행하므로 CommandNotFoundException 이 난다"
            )
            break
    return issues


# ── 런북(마크다운 코드펜스) 전용 규칙 ─────────────────────────────────────────
#
# .ps1과 규칙을 나눈 이유: .ps1은 파일 하나가 완결 절차지만, 런북은 **여러 블록이
# 순서대로 사람에게 건네지는 절차**다. 그래서 선행 스텝의 존재를 *문서 순서*로 본다.

_FENCE_OPEN_RE = re.compile(r"^[ \t]*```[ \t]*(powershell|pwsh|ps1)[ \t]*$", re.I)
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*```[ \t]*$")
# 마크다운 인용문 접두 — `> `, `>> ` 등. 인용문 안의 펜스도 붙여넣어 실행된다.
_BLOCKQUOTE_RE = re.compile(r"^[ \t]*(?:>[ \t]?)+")

# 보호 브랜치 직접 push — origin/upstream 어느 리모트든 main·master 지목이면 거부된다.
_PUSH_PROTECTED_RE = re.compile(r"\bgit\s+push\b[^\n|;]*?\b(main|master)\b")
# 선행 확인 스텝
_CLEAN_CHECK_RE = re.compile(r"\bgit\s+status\b[^\n]*--porcelain")
_RESET_HARD_RE = re.compile(r"\bgit\s+reset\b[^\n]*--hard")
# 같은 블록에서 fail-closed로 중단시키는 형태 (조건문 + 중단)
_FAIL_CLOSED_RE = re.compile(r"\bif\b[^\n]*porcelain|\b(throw|exit|return)\b", re.I)

# UTF-8 강제 — **활성화하는 대입**만 인정한다. 단순 토큰 등장(주석·설명·`="0"`)은
# 보호가 아니다: `$env:PYTHONUTF8="0"`가 뒤따르는 파이프를 전부 보호로 표시하면
# 정확히 이 규칙이 막으려는 UnicodeEncodeError가 그대로 난다(codex P2 지적).
_UTF8_ENABLE_RES = (
    re.compile(r"\$env:PYTHONUTF8\s*=\s*[\"\']?1[\"\']?"),
    re.compile(r"\$env:PYTHONIOENCODING\s*=\s*[\"\']?utf-?8", re.I),
    re.compile(r"\[Console\]::OutputEncoding\s*=[^\n]*UTF8", re.I),
    re.compile(r"\bchcp\s+65001\b"),
)
# python 출력이 콘솔을 벗어나는 형태 (파이프 / 리다이렉트).
#
# 리다이렉트는 `\s>` 로만 잡는다 — 앞이 공백이 아닌 `>`는 대개 `<플레이스홀더>`의 닫는
# 꺾쇠다(실측 오탐: `--until <파일럿종료YYYY-MM-DD> --shadow-ledger ...`가 리다이렉트로
# 잡혔다). 오탐이 있는 가드는 사람이 끄게 만들므로 좁히는 쪽을 택한다.
_PY_PIPED_RE = re.compile(r"\bpython[0-9.]*\b[^\n]*?(\||\s>+\s*\S)")

# OPS-60 ⑦ — 자동/예약 변수 대입. 뒤에 `(?![\w-])`를 둬 `$homeDir` 같은 다른 이름의
# 변수를 오탐하지 않는다. `=`만 잡고 `==`(비교)·`-eq`(비교 연산자, `=` 미포함)는
# 자연히 배제된다. `+=`/`-=` 등 복합 대입까지는 좁혀서 다루지 않는다(미탐 허용).
_AUTO_VAR_NAMES = ("home", "host", "input", "error", "args", "pwd", "matches", "profile")
_AUTO_VAR_ASSIGN_RE = re.compile(rf"\$(?:{'|'.join(_AUTO_VAR_NAMES)})(?![\w-])\s*=(?!=)", re.I)

# OPS-60 ⑧ — Invoke-WebRequest/iwr에 -UseBasicParsing 누락. 한 코드 줄 안에서만 본다.
_WEB_REQUEST_RE = re.compile(r"\b(?:Invoke-WebRequest|iwr)\b", re.I)
_USE_BASIC_PARSING_RE = re.compile(r"-UseBasicParsing\b", re.I)

# OPS-60 ⑨ — catch 안 $_.Exception.Response 무가드 프로퍼티 체인 접근. 가드는 같은
# 블록의 **앞선 줄**에서 그 표현식을 진리값으로 검사하는 `if (...)`만 인정한다(대입 후
# 별도 변수로 검사하는 형태는 미탐 허용 — 좁히는 쪽).
_RESPONSE_GUARD_IF_RE = re.compile(r"\bif\s*\([^)\n]*\$_\.Exception\.Response[^)\n]*\)", re.I)
_RESPONSE_UNGUARDED_ACCESS_RE = re.compile(r"\$_\.Exception\.Response\s*\.")

# OPS-60 ④ 평가 후 채택분 — 펜스가 `else`/`elseif`로 시작. 이 펜스 안에는 대응하는
# `if`가 있을 수 없다(있었다면 첫 코드 줄이 `else`가 아니다) — 오탐 없는 좁은 부분집합.
_BARE_ELSE_START_RE = re.compile(r"^\s*\}?\s*else(?:if)?\b", re.I)

# OPS-73 ⑩ — 셀 프롬프트 접두가 실행용 코드로 남음. `$ `는 PowerShell 코드에서 나올
# 이유가 없다(변수는 `$이름`이지 `$ `가 아니다) — 좁혀도 오탐이 없다.
_SHELL_PROMPT_PREFIX_RE = re.compile(r"^[ \t]*(?:\$ |PS>|PS [A-Za-z]:\\[^\n]*>)")

# OPS-73 ⑪ — 화살표 뒤 한국어 판정어. 주석·문자열 안의 화살표는 code(strip_noncode
# 결과)에서 이미 공백으로 지워져 자연히 면제된다(acceptance③).
_ARROW_JUDGEMENT_WORDS = (
    "존재",
    "부재",
    "성공",
    "실패",
    "통과",
    "거부",
    "완료",
    "정상",
    "오류",
    "없음",
    "있음",
    "진행중",
    "중단",
    "시작",
    "종료",
    "확인",
    "발견",
    "재현",
)
_ARROW_OUTPUT_RE = re.compile(r"[→←]\s*(?:" + "|".join(_ARROW_JUDGEMENT_WORDS) + r")")

# OPS-73 ⑫ — 커밋 해시+메시지 형태의 줄(`b64f470d  OPS-72: ... (#1065)`). 짧은 변수
# 대입(`$x = "abc1234"`)은 줄이 `$`로 시작해 이 패턴에 걸리지 않는다.
_COMMIT_HASH_LINE_RE = re.compile(r"^[ \t]*[0-9a-f]{7,40}\s+\S")


def _dequote(line: str) -> str:
    """마크다운 인용문 접두를 벗긴다 — 인용문 안의 펜스도 실행 대상이다."""
    return _BLOCKQUOTE_RE.sub("", line, count=1)


def iter_powershell_blocks(text: str) -> list[tuple[int, str]]:
    """마크다운에서 powershell 코드펜스를 (시작 줄번호, 본문)로 뽑는다.

    인용문(`> `) 안의 펜스도 대상이다 — 실측(2026-09-01): 런북 §7의 롤백 절차가 전부
    인용문 안에 있었고, 그 안에 `git reset --hard`가 있는데 가드가 **한 줄도 보지
    못했다**. 대상을 못 찾은 전수 가드는 공허하게 통과한다.
    """
    lines = text.split("\n")
    blocks: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if _FENCE_OPEN_RE.match(_dequote(lines[i])):
            body: list[str] = []
            start = i + 1
            j = start
            while j < len(lines) and not _FENCE_CLOSE_RE.match(_dequote(lines[j])):
                body.append(_dequote(lines[j]))
                j += 1
            blocks.append((i + 1, "\n".join(body)))
            i = j + 1
        else:
            i += 1
    return blocks


def check_runbook_markdown(path: pathlib.Path) -> list[str]:
    """런북 마크다운 1건 — 코드펜스를 **문서 순서**로 훑는다.

    선행 스텝(UTF-8 강제)은 위험 명령보다 *앞선 줄*에 있어야 인정한다. 청결 확인은
    더 엄격하다 — **다른(앞선) 펜스**에 있거나 같은 펜스라면 fail-closed 중단이
    있어야 한다. 같은 펜스의 `status` → `reset --hard`는 보호가 아니다: 붙여넣으면
    PowerShell이 status를 찍고 **결과와 무관하게** 곧바로 reset을 실행한다
    (codex P1 지적 — 초판은 이 형태를 테스트로 축복하고 있었다).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = iter_powershell_blocks(text)
    if not blocks:
        return []

    rows: list[tuple[int, str, str, int]] = []  # (줄번호, 원문, 코드, 블록 index)
    for bi, (line_no, body) in enumerate(blocks):
        code_lines = strip_noncode(body).split("\n")
        for off, raw_line in enumerate(body.split("\n")):
            code_line = code_lines[off] if off < len(code_lines) else ""
            rows.append((line_no + 1 + off, raw_line, code_line, bi))

    def _utf8_enabled(raw: str) -> bool:
        head = raw.split("#", 1)[0]  # 주석은 실행되지 않는다
        return any(r.search(head) for r in _UTF8_ENABLE_RES)

    utf8_at = next((i for i, r in enumerate(rows) if _utf8_enabled(r[1])), float("inf"))
    # 청결 확인이 등장한 **블록 index** — 같은 블록은 인정하지 않으므로 블록 단위로 본다.
    clean_blocks = {r[3] for r in rows if _CLEAN_CHECK_RE.search(r[2])}
    failclosed_blocks = {
        bi for bi, (_ln, body) in enumerate(blocks) if _FAIL_CLOSED_RE.search(strip_noncode(body))
    }

    issues: list[str] = []
    for line_no, body in blocks:
        issues += [f"L{line_no}+ {m}" for m in check_balance(strip_noncode(body))]

    # OPS-60 ④ 평가 후 채택분 — 펜스가 else/elseif로 시작(대응하는 if가 있을 수 없다).
    for line_no, body in blocks:
        code_lines = strip_noncode(body).split("\n")
        first_code_line = next((c for c in code_lines if c.strip()), "")
        if _BARE_ELSE_START_RE.match(first_code_line):
            issues.append(
                f"L{line_no}+: 펜스가 `else`/`elseif`로 시작 — 대응하는 `if`가 이 펜스 "
                "안에 있을 수 없다. 붙여넣기가 펜스 단위로 분리되면 이전 펜스의 if는 "
                "그 자리에서 완결 문으로 실행되고, 이 펜스의 else는 CommandNotFoundException "
                "으로 거부된다(2026-09-01 실측 유형). if/else를 한 펜스에 합친다"
            )

    # OPS-60 ⑨ 가드 추적 — 같은 블록의 앞선 줄에서 본 if(...Response...)만 인정한다.
    response_guarded_blocks: set[int] = set()

    for idx, (ln, _raw, code, bi) in enumerate(rows):
        m = _PUSH_PROTECTED_RE.search(code)
        if m:
            issues.append(
                f"L{ln}: 보호 브랜치 직접 push: {m.group(0).strip()!r} "
                "— 저장소 규칙이 'Changes must be made through a pull request'를 강제해 "
                "GH013으로 거부된다(2026-09-01 실측). 브랜치 push + PR로 바꾼다"
            )

        if _RESET_HARD_RE.search(code):
            earlier_clean = any(b < bi for b in clean_blocks)
            if not earlier_clean and bi not in failclosed_blocks:
                issues.append(
                    f"L{ln}: `git reset --hard` 앞에 **차단력 있는** 청결 확인이 없다 "
                    "— 같은 블록의 `git status --porcelain`은 보호가 아니다(붙여넣으면 "
                    "출력과 무관하게 곧바로 reset이 실행된다). 앞선 블록으로 분리해 사람이 "
                    "보게 하거나, 같은 블록이라면 비어있지 않을 때 중단하는 조건을 둔다"
                )

        if _PY_PIPED_RE.search(code) and utf8_at > idx:
            issues.append(
                f"L{ln}: python 출력을 파이프·리다이렉트하는데 앞서 UTF-8 강제가 없다 "
                "— 한국어 Windows에서 stdout이 로케일(cp949)로 인코딩돼 UnicodeEncodeError로 "
                ' 죽는다(2026-09-01 실측 2건). $env:PYTHONUTF8="1" 등을 앞에 둔다'
            )

        m = _AUTO_VAR_ASSIGN_RE.search(code)
        if m:
            issues.append(
                f"L{ln}: 자동/예약 변수 대입: {m.group(0).strip()!r} "
                "— PowerShell 자동 변수(읽기 전용)라 대입이 거부되는데, 원래 값이 이미 "
                "참이라 이후 조건문에서 '대입 실패'가 '성공'처럼 보인다. 다른 이름을 쓴다"
            )

        if _WEB_REQUEST_RE.search(code) and not _USE_BASIC_PARSING_RE.search(code):
            issues.append(
                f"L{ln}: Invoke-WebRequest/iwr에 -UseBasicParsing 이 없다 "
                "— PowerShell 5.1이 IE 엔진 파싱을 시도하다 대화형 대화상자로 정지해 "
                "무인 실행이 멈춘다. -UseBasicParsing 을 추가한다"
            )

        if _RESPONSE_GUARD_IF_RE.search(code):
            response_guarded_blocks.add(bi)
        elif _RESPONSE_UNGUARDED_ACCESS_RE.search(code) and bi not in response_guarded_blocks:
            issues.append(
                f"L{ln}: `$_.Exception.Response`를 존재 확인 없이 프로퍼티로 참조 "
                "— DNS·TLS·연결거부 같은 전송 계층 오류에서는 Response가 $null이라 "
                "NullReferenceException으로 원래 원인이 유실된다. "
                "`if ($_.Exception.Response) { ... }`로 먼저 확인한다"
            )

        if _SHELL_PROMPT_PREFIX_RE.match(code):
            issues.append(
                f"L{ln}: 셀 프롬프트 접두(`$ `·`PS>`·`PS C:\\...>`)가 실행용 코드로 남아 "
                "있다 — 실행 예시·터미널 캡처가 그대로 섞였을 가능성(OPS-73). 붙여넣으면 "
                "프롬프트 문자열 자체가 명령으로 파싱된다. 프롬프트 접두를 지운다"
            )

        if _ARROW_OUTPUT_RE.search(code):
            issues.append(
                f"L{ln}: 화살표(→/←) 뒤에 판정어가 오는 줄 — 실행 결과·증거를 실행용 "
                "펜스에 그대로 인용했을 가능성(2026-08-31 HARN-38·2026-09-10 OPS-72 사고 "
                "유형). 화살표 뒤 텍스트가 앞 명령의 추가 인자로 파싱돼 오류가 난다. "
                "증거는 인용문(`> `)으로 펜스 밖에 둔다"
            )

        if _COMMIT_HASH_LINE_RE.match(code):
            issues.append(
                f"L{ln}: 커밋 해시+메시지 형태의 줄({code.strip()[:40]!r}) — 실행 결과를 "
                "그대로 인용했을 가능성(2026-09-10 OPS-72 실측). 메시지의 `(#1234)` 같은 "
                "괄호가 PowerShell에서 식으로 파싱돼 ParserError가 난다. 증거는 펜스 밖 "
                "인용문으로 낸다"
            )

    return issues


def check_file(path: pathlib.Path) -> list[str]:
    raw = path.read_bytes()
    issues: list[str] = []
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    has_non_ascii = any(b > 0x7F for b in body)
    # BOM은 비ASCII가 있을 때만 필요하다. ASCII 전용 파일에 요구하면 변별력 없는 검사가 된다
    # (2026-08-22: backup_whymath_pg.ps1을 오탐했다 — 순수 ASCII라 BOM이 불필요하다).
    if has_non_ascii and not raw.startswith(b"\xef\xbb\xbf"):
        issues.append(
            "L1: 비ASCII 문자가 있는데 UTF-8 BOM이 없음 "
            "— PS 5.1이 로케일(cp949)로 읽어 한국어가 깨진다"
        )
    code = strip_noncode(raw.decode("utf-8-sig", errors="replace"))
    issues += check_balance(code)
    issues += check_call_before_def(code)
    return issues


def main(argv: list[str]) -> int:
    if argv[1:]:
        targets = [pathlib.Path(a) for a in argv[1:]]
    else:
        targets = sorted(pathlib.Path("scripts").rglob("*.ps1"))
        # OPS-57 — Kiki에게 건네는 PowerShell의 대부분은 런북 코드펜스다.
        targets += sorted(pathlib.Path("docs").rglob("*.md"))
        # OPS-73 — 슬래시 커맨드 문서도 Kiki에게 그대로 붙여넣기 대상으로 건네진다.
        commands_dir = pathlib.Path(".claude/commands")
        if commands_dir.is_dir():
            targets += sorted(commands_dir.glob("*.md"))
    files = [t for t in targets if t.is_file()]
    if not files:
        print("검사할 파일이 없다.")
        return 0

    failed = 0
    for f in files:
        if f.suffix.lower() == ".md":
            issues = check_runbook_markdown(f)
            if not issues and not iter_powershell_blocks(
                f.read_text(encoding="utf-8", errors="replace")
            ):
                continue  # powershell 펜스가 없는 문서는 조용히 넘긴다
        else:
            issues = check_file(f)
        if issues:
            failed += 1
            print(f"[FAIL] {f}")
            for msg in issues:
                print(f"    {msg}")
        else:
            print(f"[ok  ] {f}")
    print(f"\n검사 {len(files)}건 / 위반 {failed}건")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
