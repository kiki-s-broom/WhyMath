"""규칙 인덱스 — CLAUDE.md의 규칙이 무엇으로 집행되는지를 대장으로 (HARN-121 ②(b)·④).

왜 이 모듈이 있는가
-------------------
`docs/reviews/recurring_failure_taxonomy_2026-09-20.md` §2.6의 실측: 개별 사고의
44%는 코드로 상환됐는데, *일반화된 규칙*으로 올라간 것들은 **56%가 산문뿐**이다.
산문 규칙에는 집행 지점이 없으므로 **막고 있는지를 검증할 수 없다** — 그래서 같은
유형이 재발할 때마다 글이 한 단락 늘고, 그 글을 다음 세션이 통째로 읽는다.

이 모듈은 그 상태를 데이터로 만든다. 규칙마다 "무엇이 이것을 집행하는가"를 적고,
적히지 않은 신규 규칙을 린트가 거부한다(2026-09-20 Kiki 지정 산문 규칙 등재 동결).

CLAUDE.md 본문은 건드리지 않는다
--------------------------------
인덱스는 **규칙 제목 문자열**로 CLAUDE.md와 대응한다(2026-09-21 Kiki 승인). 헌법
본문에 ID 앵커를 박는 쪽이 견고하지만 그것은 본문 75줄을 고치는 변경이라 별도
승인이 필요하다. 제목이 바뀌면 L1이 red를 내는데, 그것은 *고칠 수 있는* red다
(인덱스의 title을 같이 고치면 된다) — 조용히 어긋나는 것보다 낫다.

규칙의 세 종류 (origin)
-----------------------
`grep -c '❌'`로 세면 75건인데 보고서는 "규칙 52건"이라 한다. 차이는 종류에 있다:

  - **incident** (28) — 사고에서 나온 규칙. 집행 코드/태스크를 요구한다.
  - **founding** (31) — 창건 원칙("단순 사진→답 풀이 앱 금지", "미성년자 PII 외부
    공유 금지"). 사고 대책이 아니므로 테스트를 요구하는 것이 말이 안 된다.
  - **extension** (16) — 기존 규칙의 확장 축(`- **확장 — ...**`). 부모를 갖는다.

founding을 인덱스에서 아예 빼지 않는 이유: 빼면 누가 ❌ 항목을 새로 추가했을 때
인덱스 **밖으로 빠져나가고**, 그러면 전수 검사(L1)가 공허해진다. 대신 status를
`policy`로 두어 "집행 코드를 요구하지 않는다"를 *명시*한다 — 빈칸으로 두면 나중에
"미측정"인지 "해당 없음"인지 구별할 수 없다(모른다 ≠ 아니다).

유예와 래칫 (L5)
----------------
동결 시점에 이미 산문뿐인 규칙이 29건이다. 즉시 위반으로 만들면 대장 전체가 red가
되고(사람이 린트를 끈다), 영원히 허용하면 "만료 없는 유예"가 된다. 그래서
`grandfathered: true`로 싣고 **건수가 늘지 않는 것만** 강제한다. 줄이는 것은 각
태스크의 몫이며, 래칫은 빚이 커지지 않음을 보장한다.

의존성: 표준 라이브러리만 (`scripts/harness/`의 공통 계약).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dc_fields
from pathlib import Path

# ── 폐쇄 집합 ────────────────────────────────────────────────────────────────

ORIGINS: tuple[str, ...] = ("incident", "founding", "extension", "guidance")

# code  = 테스트·가드·훅·CLI 게이트가 막는다
# task  = 아직 코드가 없고 백로그 태스크가 추적한다
# prose = 산문뿐 (동결 이전 항목만 허용 — grandfathered)
# policy = 집행 코드를 *요구하지 않는* 창건 원칙 (founding 전용)
STATUSES: tuple[str, ...] = ("code", "task", "prose", "policy")

RULE_ID_RE = re.compile(r"^R-\d{3}[a-z]?$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TASK_REF_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}-(?:\d{2}|[1-9]\d{2})(-[a-z0-9-]+)?$")

LEDGER_NAME = "rules.ndjson"
INDEX_DOC = "docs/standards/rule_index.md"
CONSTITUTION = "CLAUDE.md"

# ── CLAUDE.md 파싱 ───────────────────────────────────────────────────────────

_TOP_BOLD_RE = re.compile(r"^- ❌ \*\*(.+?)\*\*")
_TOP_PLAIN_RE = re.compile(r"^- ❌ (?!\*\*)(.+)$")
_EXTENSION_RE = re.compile(r"^  - \*\*(확장 —.+?)\*\*")
_HEADING_RE = re.compile(r"^#{2,3} (.+)$")
_BOLD_ITEM_RE = re.compile(r"^- \*\*(.+?)\*\*")

# `❌` 없이 규칙이 사는 절 — 여기의 볼드 항목도 규칙이다.
#
# 왜 절로 한정하는가: `- **...**` 형태는 기술 스택·문서 인덱스 등 *규칙이 아닌* 목록에도
# 쓰인다. 전역으로 잡으면 오탐이 쏟아지고, 그러면 사람이 린트를 끈다. 반대로 이 절을
# 빼면 **E 분류(Kiki 런북 결함)가 통째로 인덱스 밖으로 빠진다** — 사고 34건으로 규칙이
# 가장 많이 붙은 분류이고(규칙 13건), 그 자리가 비면 전수 검사(L1)가 공허해진다.
_GUIDANCE_SECTIONS: tuple[str, ...] = ("Kiki 개인 선호",)

# 사고 경위 단락 — 동결 대상(L3). 산문에 사고 서사를 더 쓰는 대신 대장으로 보낸다.
#
# **콜론까지 요구한다**(acceptance ④ 문면이 그렇게 적는다). 콜론 없는 "사고 경위"는
# 서사가 아니라 그것을 *언급하는* 메타 문장이다 — 실제로 CLAUDE.md의 「실수 관리」 절
# 자신이 "기존 규칙의 사고 경위 1줄 병기는 유지한다"라고 쓴다. 콜론을 빼면 그 줄이
# 위반으로 잡히고, 고칠 수 없는 위반을 보고하는 린트는 사람이 린트를 끄게 만든다.
_INCIDENT_NARRATIVE_RE = re.compile(r"사고 경위\s*[:：]")
# 대장 참조로 인정하는 표기 — 사고 대장 파일명 또는 계열 슬러그 참조.
_LEDGER_REF_RE = re.compile(r"incidents\.ndjson|incident (?:add|series|report)|HARN-118")


@dataclass(frozen=True)
class ParsedItem:
    """CLAUDE.md에서 뽑은 규칙 항목 1개."""

    origin: str
    title: str
    line: int


def parse_constitution(text: str) -> list[ParsedItem]:
    """CLAUDE.md 본문 → 규칙 항목 목록. 순수 함수 — I/O 0.

    세 형태를 구분한다(위 모듈 docstring의 origin 참조). 순서가 의미를 갖는다:
    볼드형을 먼저 보지 않으면 평문 정규식이 볼드형까지 삼킨다.
    """
    items: list[ParsedItem] = []
    section = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(1)
        bold = _TOP_BOLD_RE.match(line)
        if bold:
            items.append(ParsedItem("incident", bold.group(1), lineno))
            continue
        plain = _TOP_PLAIN_RE.match(line)
        if plain:
            items.append(ParsedItem("founding", plain.group(1).strip(), lineno))
            continue
        ext = _EXTENSION_RE.match(line)
        if ext:
            items.append(ParsedItem("extension", ext.group(1), lineno))
            continue
        if any(name in section for name in _GUIDANCE_SECTIONS):
            guidance = _BOLD_ITEM_RE.match(line)
            if guidance:
                items.append(ParsedItem("guidance", guidance.group(1), lineno))
    return items


def _narrative_blocks(text: str) -> list[tuple[int, str]]:
    """'사고 경위'를 포함한 줄 — (줄번호, 본문). L3의 판정 대상."""
    return [
        (n, line)
        for n, line in enumerate(text.splitlines(), start=1)
        if _INCIDENT_NARRATIVE_RE.search(line)
    ]


# ── 레코드 ───────────────────────────────────────────────────────────────────


@dataclass
class Rule:
    """규칙 1건 = `backlog/rules.ndjson` 1줄."""

    id: str
    slug: str
    title: str  # CLAUDE.md의 제목 문자열 그대로 — 대응 키다. 임의 수정 금지.
    origin: str
    status: str
    enforced_by: list[str] = field(default_factory=list)
    parent: str = ""  # extension이면 부모 규칙 id
    claude_md_line: int = 0
    series_id: str = ""  # 사고 대장(incidents.ndjson)의 계열 — 회차 연결
    # 유예는 **두 축**이고 서로 독립이다. 한 필드로 묶으면 코드로 상환된 규칙이
    # 자기 사고 경위 단락 때문에 L3에 걸린다(실제로 첫 구현이 그랬다).
    grandfathered: bool = False  # L2/L5 — 대책이 산문뿐인 빚
    narrative_grandfathered: bool = False  # L3 — 동결 이전 '사고 경위' 단락 보유
    note: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        tag = self.id or "(id 없음)"
        if not RULE_ID_RE.match(self.id or ""):
            errors.append(f"{tag}: id 형식 위반 (R-001 · 확장은 R-001a)")
        if not SLUG_RE.match(self.slug or ""):
            errors.append(f"{tag}: slug 형식 위반 (소문자 kebab) — {self.slug!r}")
        if not (self.title or "").strip():
            errors.append(f"{tag}: title 누락 — CLAUDE.md 대응 키이므로 비울 수 없다")
        if self.origin not in ORIGINS:
            errors.append(f"{tag}: origin '{self.origin}' 미등록 {list(ORIGINS)}")
        if self.status not in STATUSES:
            errors.append(f"{tag}: status '{self.status}' 미등록 {list(STATUSES)}")
        if self.status == "policy" and self.origin not in ("founding", "guidance"):
            errors.append(
                f"{tag}: status 'policy'는 founding 전용이다 — 사고에서 나온 규칙에 "
                f"'집행을 요구하지 않음'을 붙이면 동결이 무력해진다 (origin={self.origin})"
            )
        if self.status in ("code", "task") and not self.enforced_by:
            errors.append(
                f"{tag}: status '{self.status}'인데 enforced_by가 비어 있다 — "
                f"어디가 집행 지점인지 적지 않으면 다음 세션이 찾을 수 없다"
            )
        if self.status == "prose" and self.enforced_by:
            errors.append(f"{tag}: status 'prose'인데 enforced_by가 있다 — 상태를 고쳐라")
        if self.origin == "extension" and not self.parent:
            errors.append(f"{tag}: extension인데 parent 규칙 id가 없다")
        if self.origin != "extension" and self.parent:
            errors.append(f"{tag}: parent는 extension 전용이다 (origin={self.origin})")
        if not isinstance(self.grandfathered, bool):
            errors.append(f"{tag}: grandfathered는 bool이어야 함 ({self.grandfathered!r})")
        if not isinstance(self.narrative_grandfathered, bool):
            errors.append(
                f"{tag}: narrative_grandfathered는 bool이어야 함 "
                f"({self.narrative_grandfathered!r})"
            )
        if not isinstance(self.claude_md_line, int) or self.claude_md_line < 0:
            errors.append(f"{tag}: claude_md_line은 0 이상 정수 ({self.claude_md_line!r})")
        return errors


_FIELD_NAMES = tuple(f.name for f in dc_fields(Rule))


def from_dict(data: dict, *, source: str = "") -> tuple[Rule | None, list[str]]:
    """dict → Rule. 미등록 키는 오류다(오타가 조용히 사라지지 않게)."""
    unknown = sorted(set(data) - set(_FIELD_NAMES))
    if unknown:
        return None, [f"{source}: 미등록 필드 {unknown}"]
    missing = [k for k in ("id", "slug", "title", "origin", "status") if k not in data]
    if missing:
        return None, [f"{source}: 필수 필드 누락 {missing}"]
    return Rule(**data), []


def ledger_path(root: Path) -> Path:
    return root / "backlog" / LEDGER_NAME


def load_rules(root: Path) -> tuple[list[Rule], list[str]]:
    """대장 읽기 — (레코드, 스키마 오류). 파일 부재는 빈 대장."""
    path = ledger_path(root)
    if not path.exists():
        return [], []
    rules: list[Rule] = []
    errors: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        where = f"{LEDGER_NAME}:{lineno}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: JSON 파싱 실패 — {type(exc).__name__}: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{where}: 객체가 아님 ({type(data).__name__})")
            continue
        rule, field_errors = from_dict(data, source=where)
        if rule is None:
            errors.extend(field_errors)
            continue
        errors.extend(f"{where} {e}" for e in rule.validate())
        rules.append(rule)
    seen: dict[str, str] = {}
    for rule in rules:
        if rule.id in seen:
            errors.append(f"{rule.id}: id 중복 (이미 '{seen[rule.id]}'에 쓰였다)")
        seen[rule.id] = rule.title
    return rules, errors


def save_rules(root: Path, rules: list[Rule]) -> Path:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in rules),
        encoding="utf-8",
    )
    return path


# ── 린트 (L1~L6) ─────────────────────────────────────────────────────────────
#
# 각 검사는 *위반 상태에서 실제로 실패 신호를 내는지*가 확인된 것만 둔다
# (CLAUDE.md: 변별력 없는 검증 스텝 금지). 대응 테스트가 주입→RED·대조군→GREEN을
# 쌍으로 고정한다.


@dataclass(frozen=True)
class Finding:
    """린트 위반 1건 — check는 L1~L6, detail은 사람이 고칠 수 있는 문장."""

    check: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - 표시 전용
        return f"[{self.check}] {self.detail}"


def lint(
    *,
    constitution_text: str,
    rules: list[Rule],
    schema_errors: list[str],
    repo_root: Path | None = None,
    known_task_ids: set[str] | None = None,
    prose_baseline: int | None = None,
) -> list[Finding]:
    """규칙 인덱스 린트 — 위반 목록(빈 리스트 = green). 순수 함수에 가깝다.

    `repo_root`가 None이면 L4의 *파일 실재* 축을 건너뛴다(경로를 확인할 수 없는
    환경에서 거짓 실패를 내지 않기 위해서다). 태스크 참조 축은 `known_task_ids`가
    주어졌을 때만 본다 — **모른다 ≠ 아니다**이므로, 목록을 못 받았으면 "없는
    태스크"라고 단정하지 않는다.
    """
    findings: list[Finding] = [Finding("schema", e) for e in schema_errors]
    parsed = parse_constitution(constitution_text)

    # L6 스캔 0건은 실패 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.
    if not parsed:
        findings.append(
            Finding("L6", f"{CONSTITUTION}에서 규칙 항목을 0건 파싱했다 — 통과가 아니라 실패다")
        )
        return findings
    if not rules:
        findings.append(Finding("L6", f"{LEDGER_NAME}이 비어 있다 — 전수 검사가 성립하지 않는다"))
        return findings

    # L1 전수 귀속 — 양방향이다. 한쪽만 보면 '인덱스에만 있는 유령 규칙'을 놓친다.
    by_title = {r.title: r for r in rules}
    parsed_titles = {p.title for p in parsed}
    for item in parsed:
        if item.title not in by_title:
            findings.append(
                Finding(
                    "L1",
                    f"{CONSTITUTION}:{item.line} 의 규칙이 인덱스에 없다 — "
                    f"'{item.title[:60]}' ({item.origin})",
                )
            )
    for rule in rules:
        if rule.title not in parsed_titles:
            findings.append(
                Finding(
                    "L1",
                    f"{rule.id}: 인덱스에는 있는데 {CONSTITUTION}에 없다 — "
                    f"제목이 바뀌었거나 규칙이 삭제됐다 ('{rule.title[:60]}')",
                )
            )

    # L2 산문 동결 (2026-09-20 Kiki 지정) — 유예 대상이 아닌 신규 항목의 산문 등재 거부.
    for rule in rules:
        if rule.status == "prose" and not rule.grandfathered:
            findings.append(
                Finding(
                    "L2",
                    f"{rule.id}: 동결 이후 규칙인데 대책이 산문뿐이다 — 집행 코드(테스트·가드·훅) "
                    f"또는 추적 태스크를 enforced_by에 붙여라 ('{rule.title[:50]}')",
                )
            )

    # L3 사고 경위 동결 — 사고 서사는 CLAUDE.md가 아니라 사고 대장(HARN-118)에 쓴다.
    for lineno, line in _narrative_blocks(constitution_text):
        if _LEDGER_REF_RE.search(line):
            continue
        rule = _owning_rule(line, by_title)
        if rule is not None and rule.narrative_grandfathered:
            continue  # 동결 이전 단락 — 유예 대상
        findings.append(
            Finding(
                "L3",
                f"{CONSTITUTION}:{lineno} 에 사고 대장 참조 없는 '사고 경위' 단락이 있다 — "
                f"경위는 `backlog/incidents.ndjson`에 등재하고 여기엔 참조만 남긴다",
            )
        )

    # L4 집행 참조 실재 — 인덱스가 거짓말을 하지 않게 한다(정본화 ≠ 집행).
    for rule in rules:
        for ref in rule.enforced_by:
            findings.extend(_enforcement_findings(rule, ref, repo_root, known_task_ids))

    # L5 유예 래칫 — 빚이 커지지 않는 것만 보장한다(만료 없는 유예 금지의 현실적 형태).
    if prose_baseline is not None:
        prose_count = sum(1 for r in rules if r.status == "prose")
        if prose_count > prose_baseline:
            findings.append(
                Finding(
                    "L5",
                    f"산문뿐인 규칙이 {prose_count}건으로 기준선 {prose_baseline}건을 넘었다 — "
                    f"래칫은 줄어드는 방향으로만 열린다",
                )
            )
    return findings


def _owning_rule(line: str, by_title: dict[str, Rule]) -> Rule | None:
    """'사고 경위'가 적힌 줄이 어느 규칙의 본문인지 — 제목 포함 여부로 귀속."""
    for title, rule in by_title.items():
        if title in line:
            return rule
    return None


def _enforcement_findings(
    rule: Rule, ref: str, repo_root: Path | None, known_task_ids: set[str] | None
) -> list[Finding]:
    """집행 참조 1건의 실재 검사 — 파일 경로 또는 태스크 ID."""
    ref = ref.strip()
    if not ref:
        return [Finding("L4", f"{rule.id}: enforced_by에 빈 참조가 있다")]
    if TASK_REF_RE.match(ref):
        if known_task_ids is None:
            return []  # 목록 미제공 — 모른다 ≠ 없다
        if not any(t == ref or t.startswith(f"{ref}-") for t in known_task_ids):
            return [Finding("L4", f"{rule.id}: enforced_by 태스크 '{ref}' 가 백로그에 없다")]
        return []
    # 경로로 간주 — `path::test_name` 형태의 뒤쪽은 떼고 파일 실재만 본다.
    path_part = ref.split("::", 1)[0]
    if repo_root is None:
        return []
    if not (repo_root / path_part).exists():
        return [
            Finding(
                "L4",
                f"{rule.id}: enforced_by 경로 '{path_part}' 가 저장소에 없다 — "
                f"인덱스가 있지도 않은 집행 지점을 가리킨다",
            )
        ]
    return []


# ── 렌더 ─────────────────────────────────────────────────────────────────────

_STATUS_LABEL = {
    "code": "**code**",
    "task": "**task**",
    "prose": "**prose** ⚠️",
    "policy": "policy",
}


def render_index(rules: list[Rule], *, prose_baseline: int) -> str:
    """`docs/standards/rule_index.md` 본문. 데이터가 정본이고 이것은 렌더 결과다."""
    by_origin = {o: [r for r in rules if r.origin == o] for o in ORIGINS}
    prose = [r for r in rules if r.status == "prose"]
    out = [
        "<!-- 자동 생성 — 손편집 금지. 정본은 `backlog/rules.ndjson`이고",
        "     `python3 scripts/harness/backlog.py rules render`가 이 파일을 다시 쓴다. -->",
        "",
        "# 규칙 인덱스 — 무엇이 이 규칙을 집행하는가",
        "",
        f"`{CONSTITUTION}`의 규칙 **{len(rules)}건** 전수. 사고 유래 "
        f"{len(by_origin['incident'])} · 확장 축 {len(by_origin['extension'])} · "
        f"창건 원칙 {len(by_origin['founding'])} · Kiki 안내 {len(by_origin['guidance'])}.",
        "",
        "이 표가 있는 이유는 하나다 — **산문 규칙에는 집행 지점이 없어서 막고 있는지를**",
        "**검증할 수 없다**. 반복 실패 676건 실측에서 개별 사고의 44%는 코드로 상환됐는데,",
        "일반화된 규칙으로 올라간 것들은 56%가 산문뿐이었다",
        "(`docs/reviews/recurring_failure_taxonomy_2026-09-20.md` §2.6).",
        "",
        "## 상태가 뜻하는 것",
        "",
        "| 상태 | 뜻 |",
        "|---|---|",
        "| **code** | 테스트·가드·훅·CLI 게이트가 막는다 |",
        "| **task** | 아직 코드가 없고 백로그 태스크가 추적한다 |",
        "| **prose** ⚠️ | 산문뿐 — 갚아야 할 빚. 동결 이전 항목만 허용된다 |",
        "| policy | 창건 원칙이라 집행 코드를 *요구하지 않는다*(사고 대책이 아니다) |",
        "",
        f"산문뿐인 규칙 **{len(prose)}건** / 래칫 기준선 {prose_baseline}건. "
        "래칫은 줄어드는 방향으로만 열린다 — 늘면 린트가 exit 1.",
        "",
    ]
    for origin, heading in (
        ("incident", "사고에서 나온 규칙"),
        ("extension", "확장 축"),
        ("guidance", "Kiki 안내 규칙"),
        ("founding", "창건 원칙"),
    ):
        group = by_origin[origin]
        out += [
            f"## {heading} ({len(group)}건)",
            "",
            "| ID | 규칙 | 상태 | 집행 지점 | 계열 |",
            "|---|---|---|---|---|",
        ]
        for rule in sorted(group, key=lambda r: r.id):
            prefix = "└ " if rule.origin == "extension" else ""
            enforced = " · ".join(f"`{e}`" for e in rule.enforced_by) or "—"
            title = rule.title.replace("|", "\\|")
            out.append(
                f"| `{rule.id}` | {prefix}{title} | {_STATUS_LABEL[rule.status]} | "
                f"{enforced} | {rule.series_id or '—'} |"
            )
        out.append("")
    out += [
        "## 판정 범위",
        "",
        "`claude_md_line`은 렌더 시점의 줄 번호이고 대응 키는 **제목 문자열**이다 — ",
        f"`{CONSTITUTION}`에서 규칙 제목을 고치면 린트 L1이 red를 낸다. 그때는 인덱스의",
        "`title`을 같은 값으로 고치면 된다(조용히 어긋나는 것보다 낫다).",
        "",
    ]
    return "\n".join(out)


# ── 래칫 기준선 ──────────────────────────────────────────────────────────────
#
# 동결 시점(2026-09-21 · HARN-118 착지 직후)의 산문뿐인 규칙 수. 이 상수는
# **줄어드는 방향으로만** 고친다 — 늘리는 커밋은 빚을 키우는 것이고, 그것이 정확히
# 이 래칫이 막으려는 동작이다. 규칙 인덱스 테스트가 이 값의 단조 감소를 동결한다.
#
# 보고서 §2.6의 "rule_only 29건"과 같은 수다(독립 재계산이 일치했다).
PROSE_BASELINE = 29


def repo_task_ids(root: Path) -> set[str]:
    """백로그 태스크 식별자 — full id와 번호 프리픽스를 함께 돌려준다(L4용)."""
    ids: set[str] = set()
    tasks_dir = root / "backlog" / "tasks"
    if not tasks_dir.is_dir():
        return ids
    for path in tasks_dir.glob("*.yaml"):
        ids.add(path.stem)
        match = re.match(r"^([A-Z][A-Z0-9]*-\d+)", path.stem)
        if match:
            ids.add(match.group(1))
    return ids


def lint_repo(root: Path) -> list[Finding]:
    """저장소 현재 상태에 대한 린트 — CLI·CI가 부르는 진입점."""
    constitution = root / CONSTITUTION
    if not constitution.is_file():
        return [Finding("L6", f"{CONSTITUTION}을 읽을 수 없다 — 판정 불가(위장 통과 금지)")]
    rules, schema_errors = load_rules(root)
    return lint(
        constitution_text=constitution.read_text(encoding="utf-8"),
        rules=rules,
        schema_errors=schema_errors,
        repo_root=root,
        known_task_ids=repo_task_ids(root),
        prose_baseline=PROSE_BASELINE,
    )


def summary(rules: list[Rule]) -> dict[str, object]:
    """집계 — 주간 지표·리포트용."""
    by_status: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    for rule in rules:
        by_status[rule.status] = by_status.get(rule.status, 0) + 1
        by_origin[rule.origin] = by_origin.get(rule.origin, 0) + 1
    total = len(rules)
    prose = by_status.get("prose", 0)
    return {
        "total": total,
        "by_status": by_status,
        "by_origin": by_origin,
        "prose_count": prose,
        "prose_baseline": PROSE_BASELINE,
        "prose_ratio": round(prose / total, 4) if total else 0.0,
        "enforced_count": by_status.get("code", 0) + by_status.get("task", 0),
    }
