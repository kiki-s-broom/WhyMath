#!/usr/bin/env python3
"""런북 쓰기 블록 자가거부 가드 스캔 게이트 — 붙여넣기 흐름은 출력으로 멈추지 않는다 (HARN-106).

왜 산문 규칙이 아니라 코드인가
----------------------------
같은 형태의 사고가 **이틀 연속** 났다.

- 2026-09-14 `G-skb01` — `REACH_EXIT=2`(Docker 미가동)인데 적재 블록이 그대로 실행됐다.
  그때의 대책이 CLAUDE.md 산문 규칙 ③ "블록 간 선행 조건은 사람 판정 지점으로 끊는다"였다.
- 2026-09-15 `G-skb03` — 그 규칙을 **충실히 따른** 런북에서, `PATHS_MATCH_MAIN=False`와
  `HAS_SKIP_FLAG=False`가 **정확히 출력됐는데도** 적재 블록이 붙여넣어졌다. 옛 CLI가 돌고
  `atom_node` 적재가 0건으로 끝났다.

두 번째가 말하는 것은 분명하다 — **출력은 흐름을 멈추지 않는다.** 사람은 블록을 연달아
붙여넣고, 판정값은 스크롤 위로 사라진다. 그래서 *쓰기* 블록은 사람 판정을 최후 방어선이
아니라 보조로 내리고, **자기가 선행 판정을 재검사해 실행을 거부**해야 한다. 이 스캐너가
그것을 기계로 요구한다(CLAUDE.md 「동일 유형 텍스트 규칙 2회 실패 후 코드 착지」 선례).

무엇을 검사하는가 (4축)
----------------------
런북(`docs/ops/*runbook*.md`)의 ```powershell 펜스를 블록 단위로 보고:

- **[가드]** 쓰기 블록은 단일 최상위 `if (…) { …쓰기… } else { …이유 출력… }` 안에서만
  쓴다. 조건은 변수를 참조해야 하고(`if ($true)`는 위장이다), `else` 가지는 **무엇이
  False였는지 출력**해야 한다(침묵 가드는 보호가 아니라 위장 — 사람은 침묵을 통과로 읽는다).
- **[되읽기]** 쓰기 블록의 출력이 **고정 문자열뿐이면 위반**이다. "정리 완료" 같은 문장은
  성공·실패 양쪽에서 같은 화면을 낸다(2026-09-17 실측 사고). 변수를 끼운 출력이나 되읽기
  명령이 하나는 있어야 "쓰고 나서 실제로 바뀌었는가"에 답할 수 있다.
- **[입력 관측]** `Read-Host -AsSecureString`은 입력이 **별표조차 보이지 않아** 붙여넣기
  실패가 빈 값으로 조용히 통과한다(2026-09-17 실측: `KEY_LENGTH=0`). 그것을 쓰는 블록은
  같은 블록 안에서 길이·형태를 검증해야 한다(값은 출력하지 않는다).
- **[파서]** 닫힌 `if` 다음 **새 줄**에서 시작하는 `elseif`/`else`는 대화형 프롬프트에서
  별개 명령으로 해석돼 `CommandNotFoundException`을 낸다(2026-09-14 실측). 같은 줄의
  `} else {`만 허용한다.

표기가 아니라 구성된 결과를 본다
------------------------------
문자열 리터럴과 주석을 먼저 벗긴 뒤 **명령 위치의 토큰**만 검사한다. 그래서
`$PopulateSrc = "…/populate.py"`(경로 변수)는 쓰기가 아니고
`& $Py -m …atom_graph.populate`(실행)는 쓰기다 — 같은 글자를 담고도 판정이 갈린다.
SQL 변이는 반대로 **문자열 안을 본다**: `psql … -c "DELETE FROM …"`의 위험은 문자열
안에 있기 때문이다(그 한 가지 예외를 명시적으로 둔다).

유예 (조용히 눌러앉지 못하게)
---------------------------
기존 런북을 전건 즉시 정정하지 않으므로 그랜드파더를 둔다 — 단 **만료일 필수**이고,
유예가 가리키는 런북이 더 이상 위반이 아니면 **unmatched로 exit 1**이다(고친 뒤 유예를
안 지우면 목록이 거짓이 된다). 만료 없는 유예는 이 저장소가 금지한다.

**스캔 0건은 실패다** — 런북을 하나도 못 찾은 전수 가드는 공허하게 통과한다.

사용:  python3 scripts/ops/check_runbook_blocks.py [경로...] [--today YYYY-MM-DD]
종료:  0 통과 / 1 위반 또는 측정 실패 / 2 인자 오류
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_GLOB = "docs/ops/*runbook*.md"

_FENCE_OPEN = re.compile(r"^\s*```+\s*powershell\s*$", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"^\s*```+\s*$")

# ── 쓰기 판정 ────────────────────────────────────────────────────────────
# 명령 위치에서 이 어휘가 보이면 *상태를 바꾸는* 블록이다. 각 항목이 왜 있는지:
#   populate/backfill  — 적재·백필 CLI (SKB 계열 사고의 직접 원인)
#   upgrade/downgrade  — alembic 스키마 이행
#   grant/revoke       — 권한 부여 (좌석 CLI)
#   gates              — 대장 게이트 조작 (clear/waive — 되돌리기 어렵다)
#   Remove-Item/Set-Content/Out-File/New-Item — 파일 생성·삭제·덮어쓰기
#   SetEnvironmentVariable — 영속 환경변수 쓰기(User/Machine 스코프)
#   git push/commit/checkout -B — 원격·이력 변경
_WRITE_COMMAND_TOKENS: tuple[str, ...] = (
    "populate",
    "backfill",
    "upgrade",
    "downgrade",
    "grant",
    "revoke",
    "remove-item",
    "set-content",
    "out-file",
    "new-item",
    "setenvironmentvariable",
)
# `New-Item -ItemType Directory`는 쓰기로 세지 않는다 — 작업 폴더 스캐폴딩은 멱등하고,
# 되돌리기 어렵지도 않으며, 선행 판정이 그것에 걸리지도 않는다. 이 가드가 겨냥하는 것은
# *DB 적재·권한 부여·영속 환경변수·원격 push·파일 덮어쓰기*처럼 되돌리기 어렵거나 선행
# 판정에 종속된 쓰기다. 파일 생성 축은 `set-content`·`out-file`과 `New-Item`의 파일 형태가
# 계속 잡는다(2026-09-17 실측: 이 예외가 없으면 `eos02` 런북의 `work\eos02` 폴더 생성이
# 위반으로 잡히는데, 그 런북의 *진짜* 쓰기는 이미 `if ($KeyOk) {` 안에 있다 — 즉 가드가
# 없다고 잡는 것이 오탐이었다).
_DIRECTORY_SCAFFOLD = re.compile(r"-ItemType\s+Directory\b", re.IGNORECASE)
# 여러 토큰이 함께 있어야 쓰기인 것들 — 단독 등장은 조회일 수 있다.
_WRITE_COMMAND_PAIRS: tuple[tuple[str, ...], ...] = (
    ("git", "push"),
    ("git", "commit"),
    ("gates", "clear"),
    ("gates", "waive"),
    ("backlog.py", "done"),
    ("backlog.py", "start"),
)
# SQL 변이는 *문자열 안*을 본다 — psql에 넘기는 -c "…" 안에 위험이 있기 때문이다.
_SQL_MUTATION = re.compile(
    r"\b(?:insert\s+into|update\s+\w|delete\s+from|drop\s+table|truncate)\b", re.IGNORECASE
)
_PSQL_INVOCATION = re.compile(r"\bpsql\b", re.IGNORECASE)

# ── 되읽기·관측 판정 ─────────────────────────────────────────────────────
_READBACK_TOKENS: tuple[str, ...] = (
    "getenvironmentvariable",
    "get-itemproperty",
    "get-content",
    "get-childitem",
    "test-path",
    "select count",
    "count(*)",
    "rev-parse",
    "docker ps",
)
_SECURE_STRING = re.compile(r"-AsSecureString\b", re.IGNORECASE)
_LENGTH_CHECK = re.compile(r"\.Length\b|\bLength\b", re.IGNORECASE)

_VARIABLE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*|\$\(")
# PowerShell 자동 상수 — **변수가 아니다**. `if ($true) { …쓰기… }`는 조건에 `$`가 있으니
# 얼핏 판정을 참조하는 것처럼 보이지만 모든 입력에서 같은 가지로 간다(위장 가드).
# 2026-09-17 실측: 이 예외가 없으면 `fake_guard` 픽스처가 통과했다.
_AUTOMATIC_CONSTANTS = frozenset({"$true", "$false", "$null"})
_IF_OPEN = re.compile(r"^\s*if\s*\(")
_DANGLING_ELSE = re.compile(r"^\s*(?:\}\s*)?else(?:if)?\b")


class WaiverSyntaxError(ValueError):
    """`경로=YYYY-MM-DD` 형식 오류."""


@dataclass(frozen=True)
class Waiver:
    """유예 1건 — 저장소 상대 경로의 런북을 `until`까지만 통과시킨다."""

    path: str
    until: date


# 소급 적용 그랜드파더 (acceptance ⑤) — 2026-09-17 전수 실측으로 채웠다.
# 이 게이트가 신설되기 *전에* 쓰인 런북들이며, 전건 즉시 정정은 이 PR의 범위를 넘는다
# (런북마다 선행 판정값이 다르고, 고치려면 각 런북의 절차를 다시 설계해야 한다).
# 만료일은 S4 게이트 판정 지평(2026-12-31)에 맞춘다 — 그때 이 목록을 재확인한다.
# `skb03_atom_node_populate_runbook.md`는 이 목록에 **없다** — 사고 당사자 런북이라
# 이번에 정정했고, 그 정정본이 이 게이트의 정상 픽스처(green 축)다.
# `eos02_prompt_cache_live_runbook.md`·`ip_separation_evidence_gate_runbook.md`도 **없다** —
# 실측 결과 이미 위반 0건이다(전자는 실제 쓰기가 `if ($KeyOk) {` 안에 있고, 후자는 `gates
# clear`가 증거 판정 변수를 재검사하는 가드 안에 있다). 초판이 후자를 유예에 넣었다가
# unmatched 규칙에 걸려 지웠다 — 유예 기계의 변별력 실증 1건이다.
RUNBOOK_WAIVERS: tuple[Waiver, ...] = (
    Waiver(path="docs/ops/eos63_skill_event_reach_sample_runbook.md", until=date(2026, 12, 31)),
    Waiver(path="docs/ops/eos_relevance_triage_gate_runbook.md", until=date(2026, 12, 31)),
    Waiver(
        path="docs/ops/g_skb01_concept_behavior_skills_populate_runbook.md",
        until=date(2026, 12, 31),
    ),
    Waiver(path="docs/ops/g_skb01_skill_node_populate_runbook.md", until=date(2026, 12, 31)),
    Waiver(path="docs/ops/kice_pdf_history_purge_runbook.md", until=date(2026, 12, 31)),
    Waiver(path="docs/ops/skb04_concept_content_populate_runbook.md", until=date(2026, 12, 31)),
)


def parse_waiver(text: str) -> Waiver:
    """`경로=YYYY-MM-DD` → Waiver. 형식이 어긋나면 WaiverSyntaxError."""
    path, sep, until_text = text.rpartition("=")
    if not sep or not path:
        raise WaiverSyntaxError(f"유예 형식 오류(경로=YYYY-MM-DD 필요): {text!r}")
    try:
        until = date.fromisoformat(until_text)
    except ValueError as exc:
        raise WaiverSyntaxError(f"유예 만료일 형식 오류({type(exc).__name__}): {text!r}") from exc
    return Waiver(path=path, until=until)


@dataclass
class Block:
    """런북의 powershell 펜스 1개."""

    path: pathlib.Path
    index: int
    start_line: int
    lines: list[str] = field(default_factory=list)

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line} (블록 #{self.index})"


def strip_strings_and_comments(line: str) -> str:
    """문자열 리터럴과 주석을 벗긴 **명령 위치**만 남긴다.

    이것이 표기 변형 방어의 핵심이다: `$PopulateSrc = "…/populate.py"`는 경로를 담은
    *변수 대입*이지 실행이 아니므로 쓰기로 세면 안 된다. 문자열을 벗기면 남는 것은
    `$PopulateSrc =`뿐이고, 변수 토큰(`$…`)은 아래에서 따로 제외한다.

    PowerShell의 완전한 파싱은 하지 않는다(여기서 필요한 판정에 과하다) — 따옴표 쌍만
    보수적으로 제거하고, 닫히지 않은 따옴표는 줄 끝까지 문자열로 본다.
    """
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote is None:
            if ch in "\"'":
                quote = ch
            elif ch == "#":
                break  # 주석 — 줄 끝까지 버린다
            else:
                out.append(ch)
        elif ch == quote:
            quote = None
            out.append(" ")  # 문자열 자리를 공백으로 남겨 토큰이 붙지 않게
        i += 1
    return "".join(out)


def mask_strings_and_comments(line: str) -> str:
    """문자열·주석을 공백으로 **치환**한다 — 길이·열 위치를 보존한다.

    `strip_…`(제거)과 달리 열이 유지되므로, 한 줄 안에서 "이 쓰기가 가드 안인가"를
    가드의 중괄호 위치와 대조할 수 있다.
    """
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote is None:
            if ch in "\"'":
                quote = ch
                out.append(" ")
            elif ch == "#":
                out.extend(" " * (len(line) - len(out)))
                break
            else:
                out.append(ch)
        elif ch == quote:
            quote = None
            out.append(" ")
        else:
            out.append(" ")
    return "".join(out).ljust(len(line))


def _is_variable_name_at(masked: str, column: int) -> bool:
    """그 위치의 토큰이 `$`로 시작하는 **변수 이름**인가(실행이 아니다)."""
    start = column
    while start > 0 and (masked[start - 1].isalnum() or masked[start - 1] in "_-."):
        start -= 1
    return start > 0 and masked[start - 1] == "$"


def _command_tokens(line: str) -> list[str]:
    """명령 위치 토큰 — 변수(`$…`)는 제외한다(변수 *이름*은 실행이 아니다)."""
    bare = strip_strings_and_comments(line)
    return [t.lower() for t in re.split(r"[\s();,|]+", bare) if t and not t.startswith("$")]


@dataclass(frozen=True)
class WriteHit:
    """상태를 바꾸는 명령 1건 — 줄 번호와 **열**까지 갖는다.

    열이 필요한 이유: 권장 가드 형태가 **한 줄**이다
    (`if ($A) { …쓰기… } else { …이유… }`). 줄 단위로만 보면 그 줄이 가드 안인지 밖인지
    구분할 수 없고, 정상 런북이 위반으로 잡힌다(2026-09-17 실측: 초판이 그렇게 잡았다).
    """

    line_no: int
    column: int
    why: str


def write_hits(block: Block) -> list[WriteHit]:
    """이 블록에서 상태를 바꾸는 지점 — 줄·열·사유."""
    hits: list[WriteHit] = []
    for offset, line in enumerate(block.lines):
        line_no = block.start_line + 1 + offset
        masked = mask_strings_and_comments(line)
        lowered = masked.lower()
        found = False
        for token in _WRITE_COMMAND_TOKENS:
            column = lowered.find(token)
            if column < 0:
                continue
            if token == "new-item" and _DIRECTORY_SCAFFOLD.search(line):
                continue  # 폴더 스캐폴딩 — 위 주석 참조
            if _is_variable_name_at(masked, column):
                continue  # `$PopulateSrc` 같은 *변수 이름*은 실행이 아니다
            hits.append(WriteHit(line_no, column, f"쓰기 명령 `{token}`"))
            found = True
            break
        if found:
            continue
        for pair in _WRITE_COMMAND_PAIRS:
            columns = [lowered.find(part) for part in pair]
            if all(c >= 0 for c in columns):
                hits.append(WriteHit(line_no, max(columns), f"쓰기 명령 `{' '.join(pair)}`"))
                found = True
                break
        if found:
            continue
        # SQL 변이만은 문자열 *안*을 본다(psql -c "…"의 위험은 거기 있다).
        if _PSQL_INVOCATION.search(lowered):
            match = _SQL_MUTATION.search(line)
            if match:
                hits.append(
                    WriteHit(
                        line_no,
                        match.start(),
                        "psql SQL 변이(INSERT/UPDATE/DELETE/DROP/TRUNCATE)",
                    )
                )
    return hits


def guarded_regions(block: Block) -> list[tuple[int, int, int, int]]:
    """최상위 `if (…) { … }`의 **true 가지** 영역 — (시작줄idx, 시작열, 끝줄idx, 끝열).

    한 줄 형태와 여러 줄 형태를 **같은 코드로** 다룬다: 블록을 하나의 문자 스트림으로 보고
    중괄호를 짝지어 true 가지의 시작·끝을 잡은 뒤 (줄, 열)로 되돌린다. `} else {`를 만나면
    거기서 true 가지가 끝난다 — else 가지의 내용이 "가드 안"으로 계상되면 위장 가드를
    통과시키게 된다.

    초판은 줄 단위 중괄호 깊이만 봤고, 그래서 **권장 형태인 한 줄 가드를 통째로 놓쳤다**
    (여는 괄호와 닫는 괄호가 같은 줄이라 깊이가 0으로 돌아온다). 2026-09-17 실측에서
    정정된 SKB-03 런북이 위반으로 잡혀 발각됐다 — 가드를 고쳤는데도 red였다.
    """
    masked_lines = [mask_strings_and_comments(line) for line in block.lines]
    stream_parts: list[str] = []
    positions: list[tuple[int, int]] = []
    for row, masked in enumerate(masked_lines):
        for col, ch in enumerate(masked):
            stream_parts.append(ch)
            positions.append((row, col))
        stream_parts.append("\n")
        positions.append((row, len(masked)))
    stream = "".join(stream_parts)
    lowered = stream.lower()

    regions: list[tuple[int, int, int, int]] = []
    i = 0
    depth = 0
    while i < len(stream):
        ch = stream[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
        elif depth == 0 and lowered.startswith("if", i) and _is_word_boundary(lowered, i, 2):
            brace = stream.find("{", i)
            if brace < 0:
                break
            close = _matching_brace(stream, brace)
            if close < 0:
                break
            sr, sc = positions[min(brace + 1, len(positions) - 1)]
            er, ec = positions[close]
            regions.append((sr, sc, er, ec))
            i = close  # else 가지는 의도적으로 영역에 넣지 않는다
            continue
        i += 1
    return regions


def _is_word_boundary(text: str, index: int, length: int) -> bool:
    """`if`가 낱말로 쓰였는가 — `diff`·`notify` 같은 부분 일치를 배제한다."""
    before = text[index - 1] if index > 0 else " "
    after = text[index + length] if index + length < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _matching_brace(text: str, open_index: int) -> int:
    """`open_index`의 `{`와 짝지어지는 `}`의 위치(없으면 -1)."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def is_guarded(block: Block, hit: WriteHit) -> bool:
    """이 쓰기가 최상위 가드의 true 가지 **안**에 있는가."""
    row = hit.line_no - block.start_line - 1
    return any(
        (sr, sc) <= (row, hit.column) < (er, ec) for sr, sc, er, ec in guarded_regions(block)
    )


def guard_condition_references_a_variable(block: Block) -> bool:
    """가드 조건이 **선행 판정 변수**를 참조하는가 — `if ($true) { … }`는 위장이다.

    자동 상수(`$true`·`$false`·`$null`)는 세지 않는다. 그것만으로 이뤄진 조건은 분기하는
    척만 할 뿐 어떤 선행 판정도 재검사하지 않는다.
    """
    for line in block.lines:
        bare = strip_strings_and_comments(line)
        if not _IF_OPEN.match(bare):
            continue
        condition = _condition_text(bare)
        for match in _VARIABLE.finditer(condition):
            if match.group(0).lower() not in _AUTOMATIC_CONSTANTS:
                return True
    return False


def _condition_text(bare: str) -> str:
    """`if (…)`의 **괄호 안**만 잘라낸다 — 짝지어진 닫는 괄호까지.

    "첫 `(`부터 줄 끝까지"로 자르면 한 줄 가드의 **본문이 조건에 섞인다**. 그러면
    `if ($true) { & $Py -m …populate }`의 `$Py`가 조건 변수로 오인돼 위장 가드가 통과한다
    (2026-09-17 실측: `fake_guard` 픽스처가 그렇게 뚫었다 — 권장 형태가 한 줄이라
    이 혼입이 예외가 아니라 기본이다).
    """
    start = bare.find("(")
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(bare)):
        if bare[i] == "(":
            depth += 1
        elif bare[i] == ")":
            depth -= 1
            if depth == 0:
                return bare[start + 1 : i]
    return bare[start + 1 :]  # 닫히지 않았다 — 있는 데까지


def has_speaking_else(block: Block) -> bool:
    """`} else {`(같은 줄)가 있고 그 가지가 **무언가를 출력**하는가 — 침묵 가드 금지."""
    for offset, line in enumerate(block.lines):
        if re.search(r"\}\s*else\s*\{", strip_strings_and_comments(line)) is None:
            continue
        # else 가지의 본문 — 같은 줄의 `{` 뒤부터, 또는 다음 줄들.
        tail = line.split("else", 1)[1]
        rest = [tail, *block.lines[offset + 1 :]]
        for candidate in rest:
            if '"' in candidate or "'" in candidate or "write-" in candidate.lower():
                return True
    return False


def has_dangling_else(block: Block) -> bool:
    """닫힌 `if` 다음 **새 줄**에서 시작하는 `else`/`elseif` — 대화형 프롬프트에서 깨진다."""
    for offset, line in enumerate(block.lines):
        if not _DANGLING_ELSE.match(line):
            continue
        # 같은 줄에 `}`가 있어도, 그 앞에 실행 가능한 내용이 없으면 새 줄 시작이다.
        stripped = strip_strings_and_comments(line).strip()
        if stripped.startswith("}") and offset > 0:
            # `} else {` 형태가 *줄 맨 앞*에 홀로 오면 앞 줄에서 if가 이미 닫힌 것이다.
            prev = strip_strings_and_comments(block.lines[offset - 1]).strip()
            if prev.endswith("}"):
                return True
        elif stripped.startswith(("else", "elseif")):
            return True
    return False


_STRING_LITERAL = re.compile(r"\"([^\"]*)\"|'([^']*)'")


def outputs_only_fixed_strings(block: Block) -> bool:
    """출력이 **고정 문자열뿐**인가 — 성공·실패 양쪽에서 같은 화면을 내는 위장 검증.

    판정 대상은 *출력되는 문자열 리터럴*이지 조건절이 아니다. 초판은 "줄에 따옴표와 변수가
    함께 있으면 동적 출력"으로 봤는데, 그러면 `if ($Ready) { …쓰기… } else { "건너뜀" }`이
    통과해 버린다 — `$Ready`는 **조건**이라 화면에 나오지 않기 때문이다
    (2026-09-17 실측: `fixed_string` 픽스처가 그렇게 통과했다).

    셋 중 하나라도 있으면 "고정 문자열뿐"이 아니다:
      ⓐ 되읽기 명령(`Get-…`·`SELECT count`·`rev-parse` 등)
      ⓑ 변수를 끼운 출력 문자열(`"EXIT=$LASTEXITCODE"`)
      ⓒ 결과가 그대로 화면에 흐르는 외부 명령(`docker`·`psql`·`git`)
    """
    for line in block.lines:
        lowered = line.lower()
        if any(token in lowered for token in _READBACK_TOKENS):
            return False  # ⓐ
        for match in _STRING_LITERAL.finditer(line):
            literal = match.group(1) if match.group(1) is not None else match.group(2)
            if "$" in literal:
                return False  # ⓑ
        tokens = _command_tokens(line)
        if any(t in ("docker", "psql", "git") for t in tokens):
            return False  # ⓒ
    return True


def secure_string_unverified(block: Block) -> bool:
    """`-AsSecureString`을 쓰면서 같은 블록에서 길이·형태를 검증하지 않는가."""
    if not any(_SECURE_STRING.search(line) for line in block.lines):
        return False
    return not any(_LENGTH_CHECK.search(line) for line in block.lines)


def parse_runbook(path: pathlib.Path) -> list[Block]:
    """마크다운에서 ```powershell 펜스를 블록으로 뽑는다."""
    blocks: list[Block] = []
    current: Block | None = None
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if current is None:
            if _FENCE_OPEN.match(raw):
                current = Block(path=path, index=len(blocks) + 1, start_line=line_no)
            continue
        if _FENCE_CLOSE.match(raw):
            blocks.append(current)
            current = None
            continue
        current.lines.append(raw)
    if current is not None:  # 닫히지 않은 펜스 — 삼키지 않고 그대로 계상한다
        blocks.append(current)
    return blocks


@dataclass
class Violation:
    """위반 1건."""

    location: str
    axis: str
    detail: str


def audit_block(block: Block) -> list[Violation]:
    """블록 1개의 4축 판정 — 쓰기가 없으면 가드·되읽기 축은 적용하지 않는다."""
    violations: list[Violation] = []
    if has_dangling_else(block):
        violations.append(
            Violation(
                block.location,
                "파서",
                "닫힌 `if` 다음 새 줄의 `else`/`elseif` — 대화형 붙여넣기에서 별개 명령으로 "
                "해석돼 그 가지가 통째로 미실행된다. 같은 줄의 `} else {`로 붙여라.",
            )
        )
    if secure_string_unverified(block):
        violations.append(
            Violation(
                block.location,
                "입력 관측",
                "`-AsSecureString`은 입력이 별표조차 보이지 않아 붙여넣기 실패가 빈 값으로 "
                "조용히 통과한다. 같은 블록에서 `.Length`로 검증하라(값은 출력하지 않는다).",
            )
        )

    hits = write_hits(block)
    if not hits:
        return violations

    unguarded = [hit for hit in hits if not is_guarded(block, hit)]
    if unguarded:
        first = unguarded[0]
        violations.append(
            Violation(
                block.location,
                "가드",
                f"{first.line_no}행 {first.why} — 선행 판정을 재검사하는 자가거부 "
                '가드 밖에 있다. `if ($A -and $B) { …쓰기… } else { "WRITE_REFUSED=True" }` '
                "형태로 감싸라(닫는 중괄호와 **같은 줄**의 `} else {`).",
            )
        )
    elif not guard_condition_references_a_variable(block):
        violations.append(
            Violation(
                block.location,
                "가드",
                "가드는 있으나 조건이 변수를 참조하지 않는다 — 선행 판정을 재검사하지 않는 "
                "위장 가드다(모든 입력에서 같은 가지로 간다).",
            )
        )
    elif not has_speaking_else(block):
        violations.append(
            Violation(
                block.location,
                "가드",
                "가드에 말하는 `else` 가지가 없다 — 침묵하며 건너뛴 블록은 보호가 아니라 "
                "위장이고, 사람은 그 침묵을 통과로 읽는다. 무엇이 False였는지 출력하라.",
            )
        )

    if outputs_only_fixed_strings(block):
        violations.append(
            Violation(
                block.location,
                "되읽기",
                "쓰기 블록의 출력이 고정 문자열뿐이다 — 성공·실패 양쪽에서 같은 화면을 낸다. "
                "쓴 결과를 되읽어 값을 출력하는 것까지가 한 동작이다.",
            )
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_runbook_blocks",
        description="런북 쓰기 블록의 자가거부 가드·되읽기·입력 관측·파서 4축 스캔 (HARN-106).",
    )
    parser.add_argument("paths", nargs="*", help="검사할 런북(생략 시 docs/ops/*runbook*.md)")
    parser.add_argument("--waive", action="append", default=[], metavar="경로=YYYY-MM-DD")
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--root", default=None, help="저장소 루트(테스트 주입용)")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else _REPO_ROOT
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError as exc:
        print(f"[인자 오류] --today 형식({type(exc).__name__}): {args.today!r}", file=sys.stderr)
        return 2
    try:
        extra = tuple(parse_waiver(text) for text in args.waive)
    except WaiverSyntaxError as exc:
        print(f"[인자 오류] {exc}", file=sys.stderr)
        return 2

    targets = (
        [pathlib.Path(p) for p in args.paths] if args.paths else sorted(root.glob(DEFAULT_GLOB))
    )
    targets = [t if t.is_absolute() else (root / t) for t in targets]
    if not targets:
        print("측정 실패 — 검사 대상 런북을 하나도 찾지 못했다(스캔 0건은 통과가 아니다).")
        return 1

    waivers = {w.path: w for w in (*RUNBOOK_WAIVERS, *extra)}
    violations: list[Violation] = []
    waived_but_clean: list[str] = []
    expired: list[str] = []
    block_total = 0
    write_block_total = 0

    for path in targets:
        rel = path.relative_to(root).as_posix()
        blocks = parse_runbook(path)
        block_total += len(blocks)
        found: list[Violation] = []
        for block in blocks:
            if write_hits(block):
                write_block_total += 1
            found.extend(audit_block(block))

        waiver = waivers.get(rel)
        if waiver is None:
            violations.extend(found)
            continue
        if waiver.until < today:
            expired.append(f"{rel} (만료 {waiver.until.isoformat()})")
            violations.extend(found)
            continue
        if not found:
            waived_but_clean.append(rel)
            continue
        print(f"[WAIVED] {rel} — 위반 {len(found)}건 (until {waiver.until.isoformat()})")

    print(
        f"\n런북 {len(targets)}건 / powershell 블록 {block_total}개 / 쓰기 블록 "
        f"{write_block_total}개 / 위반 {len(violations)}건"
    )
    for violation in violations:
        print(f"  ✗ [{violation.axis}] {violation.location}\n      {violation.detail}")
    for item in expired:
        print(f"  ✗ [유예 만료] {item} — 다시 위반이다")
    for item in waived_but_clean:
        print(f"  ✗ [유예 unmatched] {item} — 위반이 아닌데 유예가 남아 있다(목록이 거짓이다)")

    failed = bool(violations or expired or waived_but_clean)
    print("판정: 실패" if failed else "판정: 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
