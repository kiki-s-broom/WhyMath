#!/usr/bin/env python3
"""런북 붙여넣기 블록 자기완결성 게이트 — 한 블록은 앞 블록이 남긴 것에 기대지 않는다 (HARN-115).

판정 기준 (정본)
----------------
Kiki에게 주는 PowerShell 블록은 **붙여넣기 한 번이 한 단위**다. 사람은 블록을 새 창에 붙일
수도, 다른 블록 사이에 붙일 수도, 하루 뒤에 다시 붙일 수도 있다. 그러므로 한 블록은 앞 블록이
설정한 **셸 변수 · 환경변수 · 현재 작업 디렉터리** 어느 것에도 의존하지 않아야 한다. 이것을
"붙여넣기 단위 자기완결성"이라 부르고, 아래 네 축으로 판정한다(CLAUDE.md 「실행 시스템 진입
경로 완전 명시」의 세 항목 — 라벨·진입·`cd` — 에 변수·목적지 축을 더한 것).

- **[라벨]** 첫 줄(빈 줄 제외)이 실행 시스템을 밝히는 주석이다 — `# [실행 시스템] Windows
  PowerShell (= Phaiakes9)`. 무엇에 붙여넣을지 모르는 블록은 엉뚱한 창에서 돈다.
- **[작업 폴더]** 첫 실행 명령보다 앞에 **절대 경로** `cd`가 있다. 상대 경로 `cd`
  (`cd src\\backend`)와 뒤늦은 `cd`는 앞 블록이 남긴 위치를 그대로 쓴다.
- **[세션 변수]** 블록이 읽는 셸 변수(`$Py`·`$WT` 등)는 **그 블록 안에서, 읽기 전에**
  정의된다. 큰따옴표 문자열 안의 `$이름`도 읽기다(치환된다). 자동 변수(`$LASTEXITCODE`·
  `$_` 등)와 환경변수(`$env:…` — 다음 축의 영역)는 제외한다.
- **[DB 목적지]** DB에 닿는 명령은 목적지를 **그 블록이 스스로** 정한다. `alembic`과
  DB 계층에 도달하는 `whymath_backend` 모듈(아래 "DB 도달 판정")은 앞에서
  `$env:WHYMATH_DATABASE_URL = …`를 대입해야 하고, `psql` 계열은 같은 줄에 목적지
  (`docker exec <컨테이너>`·`-h`와 `-p`·`postgresql://`)를 적거나 앞에서 `$env:PGHOST`와
  `$env:PGPORT`를 대입해야 한다.

그리고 붙여넣기 흐름에서 `Read-Host`가 일으키는 손상을 따로 본다(acceptance ⑥):

- **[Read-Host 가드]** 쓰기 블록의 가드 조건이 `Read-Host` 결과에 기대면 안 된다 — 기계가
  계산하는 선행 판정으로 바꿔라. 뒤에 다른 블록이 이어 붙으면 `Read-Host`가 그 블록의 첫
  줄을 입력값으로 삼켜 ①가드가 자동으로 거부되고 ②첫 줄을 잃은 다음 블록이 그대로 돈다.
- **[Read-Host 단독]** `Read-Host`를 쓰는 블록에는 "이 블록만 단독으로 붙여넣는다"는 경고가
  블록 안 주석이나 바로 앞 본문에 있어야 한다. CLAUDE.md가 `Read-Host`를 정지 수단으로
  권하는 것은 **블록이 하나일 때만** 성립한다.

왜 이 게이트가 생겼나 (HARN-115 ⑤)
----------------------------------
2026-09-18 게이트 `G-skb01-resolution-remeasure` 실행 중 Kiki가 직접 발견했다. 런북 [7-1b]
마이그레이션 블록이 `WHYMATH_DATABASE_URL`을 **앞 블록에서 상속**하도록 쓰여 있었다.
`config.py`의 기본값은 포트 5432이고 그 포트는 타 프로젝트 점유다 — 새 창에 붙여넣었다면
`alembic upgrade head`가 다른 프로젝트 DB의 스키마를 바꾸려 했을 것이다. 두 런북 게이트
(`check_runbook_blocks.py`·`check_ps_scripts.py`)는 그 의존형 블록에서도 전건 통과했다 —
이 축의 기계 집행이 없었다. 같은 런북에서 `Read-Host` 승인 가드가 다음 블록 첫 줄을 삼켜
마이그레이션 없이 다음 블록만 돌고 같은 오류가 2회 반복됐다(⑥의 근거).

DB 도달 판정 — 이름이 아니라 구성된 결과를 본다
-----------------------------------------------
`python -m whymath_backend.X`가 DB를 쓰는지는 모듈 이름으로 알 수 없다(적재 CLI는 다른
모듈의 함수로 DB에 쓴다). 그래서 `src/backend/whymath_backend`의 **정적 import 그래프**를
만들고, 진입 모듈에서 "DB 목적지를 다루는 모듈"(소스에 `database_url`·엔진·세션 팩토리가
있는 모듈 — 정의처 `config.py`는 제외)에 도달하면 DB 명령으로 본다. 과대 근사다(도달은
실행이 아니다) — 그 대가는 무해한 목적지 한 줄이고, 과소 근사의 대가는 5432 오염이다.
모듈 파일을 찾지 못하면 **DB 명령으로 본다**(모른다 ≠ 아니다 — 이름이 바뀐 모듈일 수 있다).

범위와 유예
-----------
대상은 `docs/**/*.md`·`.claude/commands/*.md`의 ```powershell 펜스다(실행 태그가 아닌 반례
블록은 스캔하지 않는다 — 반례는 `text` 등으로 적는다). 기존 문서의 위반은 **파일별 유예**로
두되, 만료일과 **위반 건수**를 함께 박는다: 건수가 늘면 새 위반이 섞인 것이고, 줄면 유예가
실제보다 넓다 — 둘 다 exit 1이다(래칫). 만료가 지나면 차단으로 바뀐다. 만료 없는 유예는
이 저장소가 금지한다. **스캔 0건은 실패다**.

사용:  python3 scripts/ops/check_runbook_self_containment.py [경로...] [--today YYYY-MM-DD]
       [--suggest-waivers]
종료:  0 통과 / 1 위반·유예 불일치·측정 실패 / 2 인자 오류
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import check_runbook_blocks as crb  # noqa: E402 — 형제 게이트의 파서·쓰기 판정 재사용(재구현 0)

_REPO_ROOT = _HERE.parents[1]
DEFAULT_GLOBS: tuple[str, ...] = ("docs/**/*.md", ".claude/commands/*.md")
DEFAULT_BACKEND = "src/backend"

# ── [라벨] ───────────────────────────────────────────────────────────────
# 실행 시스템을 밝히는 낱말. "창 B"처럼 창만 말하는 주석은 시스템을 말하지 않는다.
_SYSTEM_LABEL = re.compile(r"powershell|pwsh|phaiakes9|\bwsl\b", re.IGNORECASE)

# ── [작업 폴더] ──────────────────────────────────────────────────────────
_CD_COMMANDS = frozenset({"cd", "chdir", "sl", "set-location", "push-location", "pushd"})
# 절대 경로로 볼 수 있는 시작 — 드라이브·UNC·루트·홈·환경변수. `$변수`는 그 블록에서 이미
# 정의됐을 때만 절대다(정의 여부는 세션 변수 스캐너가 답한다).
_ABSOLUTE_TARGET = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/|~|\$env:|\$home\b)", re.IGNORECASE)
# 문장 머리에 와도 **외부 실행이 아닌** 낱말 — 출력·제어 흐름·선언.
_NON_EXECUTING_HEADS = frozenset(
    {
        "if",
        "else",
        "elseif",
        "foreach",
        "for",
        "while",
        "do",
        "try",
        "catch",
        "finally",
        "function",
        "param",
        "return",
        "exit",
        "break",
        "continue",
        "switch",
        "write-host",
        "write-output",
        "echo",
        # 작업 폴더에 기대지 않는 계산·조회 — 경로 문자열을 **만들기만** 하거나(Join/Split)
        # 셸 밖을 보지 않는다. `$Wt = Join-Path $env:TEMP "x"`를 실행으로 세면 그 뒤의 절대
        # 경로 cd가 "늦었다"는 오탐이 난다(2026-09-29 전수 실측 1건).
        "join-path",
        "split-path",
        "get-date",
        "get-command",
        "get-random",
        "new-guid",
        "get-variable",
    }
)

# ── [세션 변수] ──────────────────────────────────────────────────────────
# PowerShell 자동·선호 변수 — 셸이 늘 채워 두므로 앞 블록에서 올 수 없다(소문자 비교).
_AUTOMATIC_VARIABLES = frozenset(
    {
        "true",
        "false",
        "null",
        "_",
        "psitem",
        "args",
        "input",
        "lastexitcode",
        "matches",
        "error",
        "pwd",
        "home",
        "host",
        "pid",
        "profile",
        "psscriptroot",
        "pscommandpath",
        "myinvocation",
        "executioncontext",
        "psversiontable",
        "psedition",
        "pshome",
        "psculture",
        "psuiculture",
        "psboundparameters",
        "psdefaultparametervalues",
        "pscmdlet",
        "psstyle",
        "iswindows",
        "islinux",
        "ismacos",
        "iscoreclr",
        "ofs",
        "stacktrace",
        "this",
        "foreach",
        "switch",
        "sender",
        "event",
        "eventargs",
        "eventsubscriber",
        "nestedpromptlevel",
        "shellid",
        "consolefilename",
        "erroractionpreference",
        "progresspreference",
        "confirmpreference",
        "verbosepreference",
        "warningpreference",
        "informationpreference",
        "debugpreference",
        "whatifpreference",
        "outputencoding",
        "maximumhistorycount",
        "psnativecommandargumentpassing",
        "psnativecommanduseerroractionpreference",
    }
)
# `$scope:이름`에서 세션 변수로 보는 범위 — 나머지(`env:`·`variable:`·`function:` 등)는 아니다.
_SESSION_SCOPES = frozenset({"global", "script", "local", "private"})
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MULTI_ASSIGN = re.compile(r"^\s*(?:\$[A-Za-z_]\w*\s*,\s*)+\$[A-Za-z_]\w*\s*=(?!=)")
_VARIABLE_PARAMS = re.compile(
    r"-(?:Out|Error|Warning|Information|Pipeline)Variable\s+\+?([A-Za-z_]\w*)", re.IGNORECASE
)
_SET_VARIABLE = re.compile(
    r"\b(?:Set|New)-Variable\s+(?:-Name\s+)?['\"]?([A-Za-z_]\w*)", re.IGNORECASE
)

# ── [DB 목적지] ──────────────────────────────────────────────────────────
_DB_URL_ENV = "whymath_database_url"
_ALEMBIC = re.compile(r"(?<![\w.\\/-])alembic(?![\w.-])", re.IGNORECASE)
_MODULE_INVOCATION = re.compile(r"(?:^|\s)-m\s+(whymath_backend(?:\.[A-Za-z_]\w*)*)")
_UVICORN_APP = re.compile(r"\buvicorn\s+(whymath_backend(?:\.[A-Za-z_]\w*)*):", re.IGNORECASE)
_PYTEST = re.compile(r"(?<![\w.-])pytest(?![\w.-])", re.IGNORECASE)
_INTEGRATION = re.compile(r"integration", re.IGNORECASE)
_PSQL_FAMILY = re.compile(r"(?<![\w.-])(psql|pg_dump|pg_dumpall|pg_restore)(?![\w.-])", re.I)
_DOCKER_EXEC = re.compile(r"\bdocker\s+(?:compose\s+)?exec\b", re.IGNORECASE)
_PG_URI = re.compile(r"postgres(?:ql)?(?:\+\w+)?://", re.IGNORECASE)
_PG_HOST_FLAG = re.compile(r"(?:^|\s)(?:-h|--host)(?:\s|=)", re.IGNORECASE)
_PG_PORT_FLAG = re.compile(r"(?:^|\s)(?:-p|--port)(?:\s|=)", re.IGNORECASE)
_DB_URL_FLAG = re.compile(r"--(?:database-url|db-url|dsn)\b", re.IGNORECASE)
# DB 목적지를 **다루는** 소스의 표지 — 정의처(config.py)는 목록에서 뺀다(모든 모듈이 import한다).
_DB_MARKER = re.compile(
    r"\bdatabase_url\b|create_async_engine|\bcreate_engine\b|sessionmaker|\basyncpg\b"
    r"|\bpsycopg|whymath_backend\.db\.session"
)
_DB_MARKER_EXCLUDED = frozenset({"whymath_backend.config"})

# ── [Read-Host] ──────────────────────────────────────────────────────────
_READ_HOST = re.compile(r"(?<![\w-])read-host(?![\w-])", re.IGNORECASE)
# "이 블록만 단독으로 붙여넣는다" · "이 한 줄만 붙여넣는다" · "따로 붙여넣는다" — 표현은 달라도
# 뜻은 하나다: 뒤 블록을 이어 붙이지 마라. 붙여넣기 동사와 단독성 표지가 함께 있어야 한다.
_PASTE_VERB = re.compile(r"붙여\s*넣")
_STANDALONE_MARK = re.compile(r"단독|혼자|(?:만|따로)\s*붙여\s*넣")
_PROSE_LOOKBACK = 12  # 펜스 바로 앞 본문에서 경고 문구를 찾는 줄 수(빈 줄 제외)


@dataclass(frozen=True)
class Waiver:
    """유예 1건 — 저장소 상대 경로 파일을 `until`까지, 위반 정확히 `count`건일 때만 통과시킨다."""

    path: str
    until: date
    count: int


# 소급 유예 (acceptance ④) — 2026-09-29 전수 실측(`--suggest-waivers`)으로 채웠다. 이 게이트가
# 생기기 전에 쓰인 문서들이며, 블록마다 선행 판정·경로가 달라 한 PR에서 전건 정정은 범위를
# 넘는다. 만료는 HARN-106 유예와 같은 S4 게이트 지평(2026-12-31)이다 — 그날부터 차단이다.
# 건수를 함께 박는 이유: 파일 단위 유예만 두면 그 파일에 새로 쓰는 위반 블록이 만료일까지
# 보이지 않는다. 건수가 바뀌면(늘거나 줄거나) 이 목록을 의식적으로 고쳐야 한다.
_WAIVER_UNTIL = date(2026, 12, 31)
SELF_CONTAINMENT_WAIVERS: tuple[Waiver, ...] = (
    Waiver(path=".claude/commands/demo-doctor.md", until=_WAIVER_UNTIL, count=5),
    Waiver(path=".claude/commands/llm-perf-doctor.md", until=_WAIVER_UNTIL, count=2),
    Waiver(path="docs/architecture/db_backup_dr_runbook.md", until=_WAIVER_UNTIL, count=6),
    Waiver(path="docs/architecture/deployment_cd_runbook.md", until=_WAIVER_UNTIL, count=7),
    Waiver(path="docs/architecture/shadow_measurement_runbook.md", until=_WAIVER_UNTIL, count=1),
    Waiver(path="docs/data/license_snapshot_archive.md", until=_WAIVER_UNTIL, count=1),
    Waiver(path="docs/data/ncic.md", until=_WAIVER_UNTIL, count=4),
    Waiver(
        path="docs/legal/export_prediction_disclosure_counsel_brief.md",
        until=_WAIVER_UNTIL,
        count=8,
    ),
    Waiver(path="docs/ops/amd395_local_llm_performance.md", until=_WAIVER_UNTIL, count=10),
    Waiver(path="docs/ops/arch55_provider_battle_smoke_runbook.md", until=_WAIVER_UNTIL, count=23),
    Waiver(path="docs/ops/arch57_authoring_openrouter_runbook.md", until=_WAIVER_UNTIL, count=8),
    Waiver(path="docs/ops/coding_constitution_kiki_runbook.md", until=_WAIVER_UNTIL, count=18),
    Waiver(path="docs/ops/eos02_prompt_cache_live_runbook.md", until=_WAIVER_UNTIL, count=8),
    Waiver(path="docs/ops/eos118_seat_signal_live_runbook.md", until=_WAIVER_UNTIL, count=7),
    Waiver(
        path="docs/ops/eos121_seat_generation_diversity_runbook.md", until=_WAIVER_UNTIL, count=14
    ),
    Waiver(path="docs/ops/eos137_first_eval_runbook.md", until=_WAIVER_UNTIL, count=3),
    Waiver(
        path="docs/ops/eos23_rejected_quad_sum_classification_runbook.md",
        until=_WAIVER_UNTIL,
        count=3,
    ),
    Waiver(
        path="docs/ops/eos63_skill_event_reach_sample_runbook.md", until=_WAIVER_UNTIL, count=11
    ),
    Waiver(path="docs/ops/eos_relevance_triage_gate_runbook.md", until=_WAIVER_UNTIL, count=10),
    Waiver(path="docs/ops/g_admin06_browser_menu_call_runbook.md", until=_WAIVER_UNTIL, count=5),
    Waiver(
        path="docs/ops/g_skb01_concept_behavior_skills_populate_runbook.md",
        until=_WAIVER_UNTIL,
        count=7,
    ),
    Waiver(path="docs/ops/g_skb01_skill_node_populate_runbook.md", until=_WAIVER_UNTIL, count=7),
    Waiver(
        path="docs/ops/harn121_constitution_token_measurement_runbook.md",
        until=_WAIVER_UNTIL,
        count=1,
    ),
    Waiver(path="docs/ops/ip_separation_evidence_gate_runbook.md", until=_WAIVER_UNTIL, count=2),
    Waiver(path="docs/ops/kice_pdf_history_purge_runbook.md", until=_WAIVER_UNTIL, count=1),
    Waiver(path="docs/ops/lic03_provenance_restore_runbook.md", until=_WAIVER_UNTIL, count=6),
    Waiver(path="docs/ops/mp03_first_golden_promotion_runbook.md", until=_WAIVER_UNTIL, count=4),
    Waiver(path="docs/ops/s3_02_free_use_remeasurement_runbook.md", until=_WAIVER_UNTIL, count=10),
    Waiver(path="docs/ops/s4_16_residue_battle_round2_runbook.md", until=_WAIVER_UNTIL, count=7),
    Waiver(path="docs/ops/skb03_atom_node_populate_runbook.md", until=_WAIVER_UNTIL, count=6),
    Waiver(path="docs/ops/skb04_concept_content_populate_runbook.md", until=_WAIVER_UNTIL, count=6),
    Waiver(path="docs/ops/windows_utf8_setup.md", until=_WAIVER_UNTIL, count=16),
    Waiver(path="docs/reviews/eos_anchor_e2e_a4_2026-08-30.md", until=_WAIVER_UNTIL, count=1),
    Waiver(path="docs/reviews/mp02_canary_review_runbook.md", until=_WAIVER_UNTIL, count=7),
    Waiver(
        path="docs/reviews/mp02_first_llm_authoring_run_runbook.md", until=_WAIVER_UNTIL, count=4
    ),
    Waiver(path="docs/reviews/mp02_rerun_runbook.md", until=_WAIVER_UNTIL, count=26),
    Waiver(
        path="docs/standards/dialogue_encryption_deployment_checklist.md",
        until=_WAIVER_UNTIL,
        count=3,
    ),
    Waiver(path="docs/standards/ssm_activation_handoff.md", until=_WAIVER_UNTIL, count=15),
    Waiver(path="docs/strategy/domain_partner_handoff_2026-07.md", until=_WAIVER_UNTIL, count=2),
    Waiver(path="docs/strategy/live_cost_measurement_2026-07.md", until=_WAIVER_UNTIL, count=13),
    Waiver(path="docs/strategy/s3_pilot_briefing.md", until=_WAIVER_UNTIL, count=1),
)


class WaiverSyntaxError(ValueError):
    """`경로=YYYY-MM-DD=건수` 형식 오류."""


def parse_waiver(text: str) -> Waiver:
    """`경로=YYYY-MM-DD=건수` → Waiver. 형식이 어긋나면 WaiverSyntaxError."""
    parts = text.rsplit("=", 2)
    if len(parts) != 3 or not parts[0]:
        raise WaiverSyntaxError(f"유예 형식 오류(경로=YYYY-MM-DD=건수 필요): {text!r}")
    path, until_text, count_text = parts
    try:
        until = date.fromisoformat(until_text)
        count = int(count_text)
    except ValueError as exc:
        raise WaiverSyntaxError(f"유예 값 형식 오류({type(exc).__name__}): {text!r}") from exc
    if count < 1:
        raise WaiverSyntaxError(
            f"유예 건수는 1 이상이어야 한다(0건이면 유예가 필요 없다): {text!r}"
        )
    return Waiver(path=path, until=until, count=count)


# ═════════════════════════════════════════════════════════════════════════
# 세션 변수 스캐너
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class VariableScan:
    """블록 1개의 변수 흐름 — 줄마다 '그 줄 시작 시점에 정의된 이름'과 상속 읽기 목록."""

    defined_before_row: list[frozenset[str]] = field(default_factory=list)
    inherited: list[tuple[int, str]] = field(default_factory=list)  # (블록 내 행, 이름)
    env_assigned_before_row: list[frozenset[str]] = field(default_factory=list)


def _normalize_variable(raw: str) -> tuple[str, str] | None:
    """`$` 뒤 토큰 → (종류, 소문자 이름). 종류는 'session'·'env'. 그 밖의 드라이브는 None."""
    if ":" in raw:
        scope, _, name = raw.partition(":")
        scope = scope.lower()
        if scope == "env":
            return ("env", name.lower())
        if scope in _SESSION_SCOPES:
            return ("session", name.lower())
        return None  # variable:·function:·alias:·using: 등 — 이 게이트의 대상이 아니다
    return ("session", raw.lower())


def scan_variables(lines: list[str]) -> VariableScan:
    """블록을 앞에서부터 읽으며 셸 변수의 정의·읽기 순서를 기록한다.

    PowerShell을 완전히 파싱하지는 않는다 — 여기서 필요한 것은 "읽기가 정의보다 먼저인가"
    하나다. 그래서 문자열 상태(작은따옴표=치환 없음 · 큰따옴표=치환 있음 · here-string)와
    주석만 추적하고, 대입은 `$이름` 뒤의 `=`(비교 연산자는 `-eq`라 `=`와 겹치지 않는다)로 본다.
    PowerShell은 우변을 먼저 평가하므로 `$X = $X + 1`의 우변 `$X`는 **앞 블록의 값**이다 —
    그래서 대입은 문장이 끝날 때(`;`·`{`·`}`·`|`·줄 끝) 정의로 확정한다.
    """
    scan = VariableScan()
    defined: set[str] = set()
    env_defined: set[str] = set()
    pending: set[str] = set()
    pending_env: set[str] = set()
    reported: set[str] = set()
    here: str | None = None  # here-string 종류('"' 또는 "'")
    block_comment = False

    def flush() -> None:
        defined.update(pending)
        pending.clear()
        env_defined.update(pending_env)
        pending_env.clear()

    def use(row: int, name: str) -> None:
        if name in _AUTOMATIC_VARIABLES or name in defined or name in reported:
            return
        reported.add(name)
        scan.inherited.append((row, name))

    for row, raw in enumerate(lines):
        scan.defined_before_row.append(frozenset(defined))
        scan.env_assigned_before_row.append(frozenset(env_defined))
        if here is not None:
            if raw.lstrip().startswith(here + "@"):
                here = None
            elif here == '"':
                for match in re.finditer(r"(?<!`)\$(\{[^}]+\}|[A-Za-z_][\w]*(?::[\w]+)?)", raw):
                    kind_name = _normalize_variable(match.group(1).strip("{}"))
                    if kind_name and kind_name[0] == "session":
                        use(row, kind_name[1])
            continue
        multi = _MULTI_ASSIGN.match(raw)
        lhs_end = 0  # 다중 대입 좌변의 끝 — 그 안의 `$이름`은 읽기가 아니라 정의다
        if multi:
            lhs_end = multi.end()
            for name in re.findall(r"\$([A-Za-z_]\w*)", multi.group(0)):
                pending.add(name.lower())
        masked = crb.mask_strings_and_comments(raw)
        for match in _VARIABLE_PARAMS.finditer(masked):
            pending.add(match.group(1).lower())
        for match in _SET_VARIABLE.finditer(raw):
            pending.add(match.group(1).lower())

        quote: str | None = None
        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            if block_comment:
                if raw.startswith("#>", i):
                    block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if quote == "'":
                if ch == "'":
                    if i + 1 < n and raw[i + 1] == "'":
                        i += 2  # '' — 작은따옴표 이스케이프
                        continue
                    quote = None
                i += 1
                continue
            if quote == '"':
                if ch == "`":
                    i += 2  # 백틱 이스케이프 — `$ 는 치환이 아니다
                    continue
                if ch == '"':
                    quote = None
                    i += 1
                    continue
                if ch == "$":
                    i = _consume_variable(raw, i, row, use, pending, pending_env, in_string=True)
                    continue
                i += 1
                continue
            # 코드 위치
            if raw.startswith("<#", i):
                block_comment = True
                i += 2
                continue
            if ch == "#":
                break
            if ch == "`":
                i += 2
                continue
            if ch == "@" and i + 1 < n and raw[i + 1] in "\"'" and not raw[i + 2 :].strip():
                here = raw[i + 1]
                break
            if ch == "@" and i + 1 < n and (raw[i + 1].isalpha() or raw[i + 1] == "_"):
                ident = _IDENT.match(raw, i + 1)
                if ident:
                    use(row, ident.group(0).lower())  # 스플랫 `@Args`는 `$Args`의 읽기다
                    i = ident.end()
                    continue
            if ch in "'\"":
                quote = ch
                i += 1
                continue
            if ch in ";{}|":
                flush()
                i += 1
                continue
            if ch == "$":
                if i < lhs_end:  # 다중 대입 좌변 — 정의는 위에서 등록했다(읽기로 세지 않는다)
                    i = _consume_variable(raw, i, row, _ignore, set(), set(), in_string=False)
                    continue
                i = _consume_variable(raw, i, row, use, pending, pending_env, in_string=False)
                continue
            i += 1
        flush()
    return scan


def _ignore(_row: int, _name: str) -> None:
    """읽기를 기록하지 않는 자리표시 콜백 — 토큰 끝만 필요할 때 쓴다."""


def _consume_variable(
    raw: str,
    i: int,
    row: int,
    use: Callable[[int, str], None],
    pending: set[str],
    pending_env: set[str],
    *,
    in_string: bool,
) -> int:
    """`raw[i] == '$'`에서 변수 토큰 하나를 읽고 정의·읽기를 기록한 뒤 다음 위치를 돌려준다."""
    n = len(raw)
    if i + 1 >= n:
        return i + 1
    nxt = raw[i + 1]
    if nxt == "(":
        return i + 2  # `$( … )` 부분식 — 안쪽은 계속 코드/문자열로 읽는다
    if nxt == "{":
        close = raw.find("}", i + 2)
        if close < 0:
            return n
        token = raw[i + 2 : close]
        end = close + 1
    else:
        match = re.match(r"[A-Za-z_][\w]*(?::[A-Za-z_][\w]*)?", raw[i + 1 :])
        if not match:
            return i + 1  # `$?`·`$$`·`$^` 등 — 자동 변수
        token = match.group(0)
        end = i + 1 + match.end()
    kind_name = _normalize_variable(token)
    if kind_name is None:
        return end
    kind, name = kind_name
    if in_string:
        if kind == "session":
            use(row, name)
        return end
    rest = raw[end:]
    stripped = rest.lstrip()
    is_assign = stripped.startswith("=") and not stripped.startswith("==")
    is_compound = bool(re.match(r"(?:\+|-|\*|/|%|\?\?)=", stripped))
    is_foreach_var = bool(re.match(r"in\b", stripped, re.IGNORECASE)) and bool(
        re.search(r"foreach\s*\(\s*$", raw[:i], re.IGNORECASE)
    )
    if kind == "env":
        if is_assign:
            pending_env.add(name)
        return end
    if is_assign or is_foreach_var:
        pending.add(name)
    elif is_compound:
        use(row, name)
        pending.add(name)
    else:
        use(row, name)
    return end


# ═════════════════════════════════════════════════════════════════════════
# 문장 분해 · 작업 폴더
# ═════════════════════════════════════════════════════════════════════════
def _statements(masked: str) -> list[tuple[int, str]]:
    """문자열·주석을 가린 줄을 `;`·`{`·`}`로 나눈 문장들 — (시작 열, 본문)."""
    out: list[tuple[int, str]] = []
    start = 0
    for idx, ch in enumerate(masked + ";"):
        if ch in ";{}":
            text = masked[start:idx]
            if text.strip():
                out.append((start, text))
            start = idx + 1
    return out


def _head_word(statement: str) -> str:
    """문장의 첫 낱말(소문자) — 대입·호출·출력의 구분에 쓴다."""
    stripped = statement.strip()
    match = re.match(r"[A-Za-z_][\w.-]*", stripped)
    return match.group(0).lower() if match else ""


def _is_executing(statement: str) -> bool:
    """이 문장이 **외부 명령을 실행**하는가 — 작업 폴더에 기댈 수 있는 첫 지점의 판정.

    실행으로 본다: 호출 연산자 `&` · 맨 앞의 명령 낱말(제어 흐름·출력 제외) · 우변이
    명령으로 시작하는 대입(`$x = Get-Content rel.txt`·`$x = (Resolve-Path ".")`).
    """
    if "&" in statement:
        return True
    stripped = statement.strip()
    if not stripped:
        return False
    if stripped.startswith("$") or stripped.startswith("["):
        if "=" not in stripped:
            return False
        rhs = stripped.split("=", 1)[1].strip().lstrip("(").strip()
        head = _head_word(rhs)
        return bool(head) and head not in _NON_EXECUTING_HEADS and not rhs.startswith("[")
    if stripped[0] in "(\"'@":
        return False
    head = _head_word(stripped)
    return bool(head) and head not in _NON_EXECUTING_HEADS and head not in _CD_COMMANDS


def _cd_target(raw_statement: str) -> str:
    """cd 문장의 대상 문자열(따옴표 제거) — `-Path`/`-LiteralPath` 형태도 받는다.

    대상이 괄호 식이면(`cd (Join-Path $Wt "src\\web")`) 그 식의 **첫 인자**가 대상의 뿌리다 —
    식이 절대 경로를 계산하는지는 뿌리가 절대인지로 정해진다.
    """
    rest = re.sub(r"^\s*[A-Za-z-]+\s*", "", raw_statement, count=1)
    rest = re.sub(r"^-(?:Literal)?Path\s+", "", rest, flags=re.IGNORECASE)
    rest = rest.strip()
    if rest.startswith("("):
        rest = re.sub(r"^\(\s*(?:Join-Path|Resolve-Path|Convert-Path)?\s*", "", rest, flags=re.I)
        rest = re.sub(r"^-(?:Literal)?Path\s+", "", rest, flags=re.IGNORECASE)
        rest = re.split(r"\s", rest.strip(), maxsplit=1)[0]
    return rest.strip().strip("\"'").strip()


# ═════════════════════════════════════════════════════════════════════════
# DB 도달 판정 — 정적 import 그래프
# ═════════════════════════════════════════════════════════════════════════
class DbReach:
    """`whymath_backend` 모듈이 DB 목적지를 다루는 코드에 **정적으로 도달**하는가."""

    def __init__(self, backend_root: pathlib.Path) -> None:
        self._root = backend_root
        self._modules: dict[str, pathlib.Path] | None = None
        self._graph: dict[str, set[str]] = {}
        self._targets: set[str] = set()
        self._memo: dict[str, bool] = {}

    def _load(self) -> dict[str, pathlib.Path]:
        if self._modules is not None:
            return self._modules
        modules: dict[str, pathlib.Path] = {}
        package = self._root / "whymath_backend"
        if package.is_dir():
            for path in package.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                name = ".".join(path.relative_to(self._root).with_suffix("").parts)
                if name.endswith(".__init__"):
                    name = name[: -len(".__init__")]
                modules[name] = path
        self._modules = modules
        for name, path in modules.items():
            text = path.read_text(encoding="utf-8")
            if name not in _DB_MARKER_EXCLUDED and _DB_MARKER.search(text):
                self._targets.add(name)
            self._graph[name] = self._imports(name, path, text, modules)
        return modules

    @staticmethod
    def _imports(
        name: str, path: pathlib.Path, text: str, modules: dict[str, pathlib.Path]
    ) -> set[str]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                    target = ".".join(base + ([node.module] if node.module else []))
                else:
                    target = node.module or ""
                found.add(target)
                found.update(f"{target}.{alias.name}" for alias in node.names)
        return {m for m in found if m in modules}

    def reaches_db(self, module: str) -> bool:
        """진입 모듈 → DB 표지 모듈 도달 여부. **모듈을 찾지 못하면 True**(모른다 ≠ 아니다)."""
        modules = self._load()
        if module not in modules:
            return True
        return self._walk(module, set())

    def _walk(self, module: str, stack: set[str]) -> bool:
        if module in self._memo:
            return self._memo[module]
        if module in self._targets:
            self._memo[module] = True
            return True
        if module in stack:
            return False
        stack.add(module)
        result = any(self._walk(dep, stack) for dep in self._graph.get(module, ()))
        stack.discard(module)
        self._memo[module] = result
        return result


# ═════════════════════════════════════════════════════════════════════════
# 블록 판정
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class Violation:
    """위반 1건 — `axis`가 `WARNING_AXIS`면 차단하지 않는 경고다."""

    location: str
    axis: str
    detail: str


# 쓰기 가드가 Read-Host 결과에 기대는 것은 **경고**다(acceptance ⑥은 이 축을 "경고하고", 단독
# 경고 문구 축은 "확인한다"로 나눠 적었다). 사람만 아는 사실("증적을 이미 전달했는가")을 확인하는
# 파괴적 블록처럼 기계 판정으로 바꿀 수 없는 정당한 쓰임이 있고, 그 블록도 단독 붙여넣기 경고는
# **반드시** 갖춰야 한다(그쪽은 차단). 경고는 매 실행 출력되어 사라지지 않는다.
WARNING_AXIS = "Read-Host 가드 · 경고"


def _first_code_line(lines: list[str]) -> str:
    return next((line.strip() for line in lines if line.strip()), "")


def _prose_before(file_lines: list[str], fence_line: int, previous_end: int) -> list[str]:
    """펜스 바로 앞 본문(이전 블록 끝 이후 · 빈 줄 제외 최대 `_PROSE_LOOKBACK`줄)."""
    window = file_lines[previous_end : fence_line - 1]
    return [line for line in window if line.strip()][-_PROSE_LOOKBACK:]


def _has_standalone_warning(texts: list[str]) -> bool:
    return any(_PASTE_VERB.search(t) and _STANDALONE_MARK.search(t) for t in texts)


def audit_block(
    block: crb.Block, db: DbReach, prose_before: list[str] | None = None
) -> list[Violation]:
    """블록 1개의 자기완결성(4축)과 Read-Host(2축) 판정."""
    violations: list[Violation] = []
    lines = block.lines
    loc = block.location

    # [라벨]
    first = _first_code_line(lines)
    if not (first.startswith("#") and _SYSTEM_LABEL.search(first)):
        violations.append(
            Violation(
                loc,
                "라벨",
                "첫 줄이 실행 시스템 라벨 주석이 아니다 — `# [실행 시스템] Windows PowerShell "
                "(= Phaiakes9)`처럼 어디에 붙여넣는지 밝혀라.",
            )
        )

    scan = scan_variables(lines)

    # [작업 폴더] — 첫 실행 문장보다 앞에 절대 경로 cd가 있어야 한다.
    cd_row: int | None = None
    cd_problem: str | None = None
    first_exec: int | None = None
    for row, raw in enumerate(lines):
        masked = crb.mask_strings_and_comments(raw)
        for start, statement in _statements(masked):
            head = _head_word(statement)
            if head in _CD_COMMANDS:
                if cd_row is None and cd_problem is None:
                    raw_statement = raw[start : start + len(statement)]
                    target = _cd_target(raw_statement)
                    variable = re.match(r"\$(?:\{([^}]+)\}|([A-Za-z_]\w*))", target)
                    if _ABSOLUTE_TARGET.match(target):
                        cd_row = row
                    elif variable and not target.lower().startswith("$env:"):
                        name = (variable.group(1) or variable.group(2)).lower()
                        if name in scan.defined_before_row[row] or name in _AUTOMATIC_VARIABLES:
                            cd_row = row
                        else:
                            cd_problem = (
                                f"{row + 1}행 `cd`의 대상 `${name}`이 블록 안에서 정의되지 않았다"
                            )
                    else:
                        cd_problem = (
                            f"{row + 1}행 `cd {target}`는 상대 경로다 — 앞 블록이 남긴 위치에 "
                            "기댄다"
                        )
                continue
            if first_exec is None and _is_executing(statement):
                first_exec = row
    if cd_row is None:
        detail = cd_problem or "절대 경로 `cd`가 없다"
        violations.append(
            Violation(
                loc,
                "작업 폴더",
                f"{detail}. 첫 실행 명령보다 앞에 `cd C:\\Users\\kiki\\Desktop\\__AI\\WhyMath`처럼 "
                "절대 경로로 들어가라.",
            )
        )
    elif first_exec is not None and first_exec < cd_row:
        violations.append(
            Violation(
                loc,
                "작업 폴더",
                f"{first_exec + 1}행의 실행 명령이 {cd_row + 1}행의 `cd`보다 앞에 있다 — 그 명령은 "
                "앞 블록이 남긴 위치에서 돈다.",
            )
        )

    # [세션 변수]
    if scan.inherited:
        names = ", ".join(f"${name}({row + 1}행)" for row, name in scan.inherited[:6])
        more = "" if len(scan.inherited) <= 6 else f" 외 {len(scan.inherited) - 6}개"
        violations.append(
            Violation(
                loc,
                "세션 변수",
                f"블록 안에서 정의되기 전에 읽는 변수: {names}{more} — 앞 블록의 값을 물려받는다. "
                "읽기 전에 이 블록에서 대입하라.",
            )
        )

    # [DB 목적지]
    violations.extend(_db_destination_violations(block, db, scan))

    # [Read-Host 가드]·[Read-Host 단독]
    read_host_rows = [
        row
        for row, raw in enumerate(lines)
        if _READ_HOST.search(crb.mask_strings_and_comments(raw))
    ]
    if read_host_rows:
        comment_texts = [line for line in lines if line.lstrip().startswith("#")]
        if not _has_standalone_warning(comment_texts + (prose_before or [])):
            violations.append(
                Violation(
                    loc,
                    "Read-Host 단독",
                    f"{read_host_rows[0] + 1}행이 `Read-Host`를 쓰는데 '이 블록만 단독으로 "
                    "붙여넣는다'는 경고가 없다 — 뒤 블록을 이어 붙이면 그 첫 줄이 입력값으로 "
                    "삼켜진다. 블록 안 주석이나 바로 앞 본문에 적어라.",
                )
            )
        guard_row = _read_host_guard_row(block)
        if guard_row is not None:
            violations.append(
                Violation(
                    loc,
                    WARNING_AXIS,
                    f"{guard_row + 1}행 쓰기 가드의 조건이 `Read-Host` 결과에 기댄다 — 붙여넣기 "
                    "흐름에서는 다음 블록 첫 줄이 그 입력이 된다. 기계가 계산하는 선행 판정으로 "
                    "바꿔라.",
                )
            )
    return violations


def _db_destination_violations(
    block: crb.Block, db: DbReach, scan: VariableScan
) -> list[Violation]:
    """DB에 닿는 명령마다 목적지가 **그 블록 안에서** 정해졌는가."""
    out: list[Violation] = []
    lines = block.lines
    integration_block = bool(_INTEGRATION.search("\n".join(lines)))
    for row, raw in enumerate(lines):
        masked = crb.mask_strings_and_comments(raw)
        for start, statement in _statements(masked):
            raw_statement = raw[start : start + len(statement)]
            env_before = scan.env_assigned_before_row[row] | _same_line_env(raw[:start])
            reason = _db_command_reason(statement, db, integration_block)
            if reason is not None:
                if _DB_URL_ENV not in env_before and not _DB_URL_FLAG.search(statement):
                    out.append(
                        Violation(
                            block.location,
                            "DB 목적지",
                            f"{row + 1}행 {reason}가 DB 목적지를 이 블록에서 정하지 않는다 — "
                            "`$env:WHYMATH_DATABASE_URL`을 물려받거나 기본값(5432 · 타 프로젝트 "
                            "점유)으로 떨어진다. 그 앞에 `$env:WHYMATH_DATABASE_URL = "
                            '"postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"`를 두어라.',
                        )
                    )
                    return out  # 블록당 1건 — 같은 원인의 반복 보고는 소음이다
                continue
            psql = _PSQL_FAMILY.search(statement)
            if psql and not _psql_destination_explicit(raw_statement, masked, env_before):
                out.append(
                    Violation(
                        block.location,
                        "DB 목적지",
                        f"{row + 1}행 `{psql.group(1)}`의 목적지가 이 블록에서 정해지지 않는다 — "
                        "같은 줄에 `docker exec whymath-pg` · `-h`와 `-p` · `postgresql://` 중 "
                        "하나를 적거나, 앞에서 `$env:PGHOST`·`$env:PGPORT`를 대입하라.",
                    )
                )
                return out
    return out


def _same_line_env(prefix: str) -> set[str]:
    """같은 줄에서 앞 문장이 대입한 환경변수 — `$env:X = …; alembic …` 형태."""
    return {m.group(1).lower() for m in re.finditer(r"\$env:([A-Za-z_]\w*)\s*=(?!=)", prefix)}


def _db_command_reason(statement: str, db: DbReach, integration_block: bool) -> str | None:
    """이 문장이 WHYMATH_DATABASE_URL을 읽는 DB 명령이면 그 사유 문자열."""
    if _ALEMBIC.search(statement):
        return "`alembic`"
    for pattern in (_MODULE_INVOCATION, _UVICORN_APP):
        match = pattern.search(statement)
        if match and db.reaches_db(match.group(1)):
            return f"`{match.group(1)}`(DB 계층에 정적으로 도달)"
    if _PYTEST.search(statement) and integration_block:
        return "통합 `pytest`"
    return None


def _psql_destination_explicit(raw_statement: str, masked: str, env_before: frozenset[str]) -> bool:
    if _DOCKER_EXEC.search(masked):
        return True
    if _PG_URI.search(raw_statement):
        return True
    if _PG_HOST_FLAG.search(raw_statement) and _PG_PORT_FLAG.search(raw_statement):
        return True
    return {"pghost", "pgport"} <= env_before


def _read_host_guard_row(block: crb.Block) -> int | None:
    """쓰기 가드의 조건이 Read-Host 결과(직접 호출 또는 오염된 변수)를 참조하는 행."""
    if not crb.write_hits(block):
        return None
    tainted: set[str] = set()
    for raw in block.lines:
        masked = crb.mask_strings_and_comments(raw)
        for match in re.finditer(r"\$([A-Za-z_]\w*)\s*=(?!=)([^;]*)", masked):
            rhs = match.group(2)
            if _READ_HOST.search(rhs) or any(
                re.search(rf"\${re.escape(t)}\b", rhs, re.IGNORECASE) for t in tainted
            ):
                tainted.add(match.group(1).lower())
    for row, raw in enumerate(block.lines):
        bare = crb.strip_strings_and_comments(raw)
        if not crb._IF_OPEN.match(bare):
            continue
        condition = crb._condition_text(bare)
        if _READ_HOST.search(condition):
            return row
        for name in re.findall(r"\$([A-Za-z_]\w*)", condition):
            if name.lower() in tainted:
                return row
    return None


# ═════════════════════════════════════════════════════════════════════════
# 파일 스캔 · 유예
# ═════════════════════════════════════════════════════════════════════════
def audit_file(
    path: pathlib.Path, db: DbReach, display: pathlib.Path | None = None
) -> tuple[int, list[Violation]]:
    """파일 1개 — (블록 수, 위반 목록). `display`가 있으면 위치를 그 경로로 적는다."""
    blocks = crb.parse_runbook(path)
    file_lines = path.read_text(encoding="utf-8").splitlines()
    violations: list[Violation] = []
    previous_end = 0
    for block in blocks:
        if display is not None:
            block.path = display
        prose = _prose_before(file_lines, block.start_line, previous_end)
        violations.extend(audit_block(block, db, prose))
        previous_end = block.start_line + len(block.lines) + 1
    return len(blocks), violations


def _targets(root: pathlib.Path, paths: list[str]) -> list[pathlib.Path]:
    if paths:
        resolved = [pathlib.Path(p) for p in paths]
        return [p if p.is_absolute() else (root / p) for p in resolved]
    found: set[pathlib.Path] = set()
    for pattern in DEFAULT_GLOBS:
        found.update(root.glob(pattern))
    return sorted(p for p in found if p.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_runbook_self_containment",
        description="런북 붙여넣기 블록 자기완결성(라벨·작업 폴더·세션 변수·DB 목적지)과 "
        "Read-Host 손상 스캔 (HARN-115).",
    )
    parser.add_argument(
        "paths", nargs="*", help="검사할 마크다운(생략 시 docs/**·.claude/commands)"
    )
    parser.add_argument("--waive", action="append", default=[], metavar="경로=YYYY-MM-DD=건수")
    parser.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--root", default=None, help="저장소 루트(테스트 주입용)")
    parser.add_argument("--backend-root", default=None, help="백엔드 루트(기본 <root>/src/backend)")
    parser.add_argument(
        "--no-builtin-waivers",
        action="store_true",
        help="내장 유예를 쓰지 않는다(테스트·전수 실측용)",
    )
    parser.add_argument(
        "--suggest-waivers",
        action="store_true",
        help="위반 파일마다 유예 한 줄(경로·만료·건수)을 출력하고 exit 0",
    )
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else _REPO_ROOT
    backend = pathlib.Path(args.backend_root) if args.backend_root else root / DEFAULT_BACKEND
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        extra = tuple(parse_waiver(text) for text in args.waive)
    except (ValueError, WaiverSyntaxError) as exc:
        print(f"[인자 오류] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    targets = _targets(root, args.paths)
    if not targets:
        print("측정 실패 — 검사 대상 마크다운을 하나도 찾지 못했다(스캔 0건은 통과가 아니다).")
        return 1

    db = DbReach(backend)
    builtin = () if args.no_builtin_waivers else SELF_CONTAINMENT_WAIVERS
    waivers = {w.path: w for w in (*builtin, *extra)}
    seen: set[str] = set()
    failures: list[str] = []
    violations: list[Violation] = []
    block_total = 0
    per_file: dict[str, int] = {}

    warnings: list[Violation] = []
    for path in targets:
        rel = path.relative_to(root).as_posix()
        seen.add(rel)
        count, everything = audit_file(path, db, pathlib.Path(rel))
        block_total += count
        warnings.extend(v for v in everything if v.axis == WARNING_AXIS)
        found = [v for v in everything if v.axis != WARNING_AXIS]
        if found:
            per_file[rel] = len(found)
        waiver = waivers.get(rel)
        if waiver is None:
            violations.extend(found)
            continue
        if waiver.until < today:
            failures.append(f"[유예 만료] {rel} (만료 {waiver.until.isoformat()}) — 다시 위반이다")
            violations.extend(found)
        elif len(found) > waiver.count:
            failures.append(
                f"[유예 초과] {rel} — 위반 {len(found)}건 > 유예 {waiver.count}건: 새 위반이 섞였다"
            )
            violations.extend(found)
        elif len(found) < waiver.count:
            failures.append(
                f"[유예 과대] {rel} — 위반 {len(found)}건 < 유예 {waiver.count}건: 고친 만큼 "
                "유예 건수를 줄여라(0건이면 항목을 지워라)"
            )
        else:
            print(f"[WAIVED] {rel} — 위반 {len(found)}건 (until {waiver.until.isoformat()})")

    if not args.paths:
        for path_key in sorted(set(waivers) - seen):
            failures.append(f"[유예 unmatched] {path_key} — 스캔 대상에 없다(목록이 거짓이다)")

    if args.suggest_waivers:
        for rel, count in sorted(per_file.items()):
            print(f'    Waiver(path="{rel}", until=_WAIVER_UNTIL, count={count}),')
        return 0

    if block_total == 0:
        print("측정 실패 — powershell 블록을 하나도 찾지 못했다(스캔 0건은 통과가 아니다).")
        return 1

    axes: dict[str, int] = {}
    for violation in violations:
        axes[violation.axis] = axes.get(violation.axis, 0) + 1
    axis_text = " · ".join(f"{k} {v}" for k, v in sorted(axes.items())) or "없음"
    print(
        f"\n마크다운 {len(targets)}건 / powershell 블록 {block_total}개 / 위반 {len(violations)}건 "
        f"({axis_text}) / 경고 {len(warnings)}건"
    )
    for violation in violations:
        print(f"  ✗ [{violation.axis}] {violation.location}\n      {violation.detail}")
    for warning in warnings:
        print(f"  ⚠ [{warning.axis}] {warning.location}\n      {warning.detail}")
    for item in failures:
        print(f"  ✗ {item}")
    failed = bool(violations or failures)
    print("판정: 실패" if failed else "판정: 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
