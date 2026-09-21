"""사고 대장 — 반복 실패의 회차 계수를 단일 대장으로 (HARN-118).

왜 이 모듈이 있는가
-------------------
이 저장소는 같은 유형의 실패를 반복해 왔고, 그때마다 회차를 *산문으로* 셌다
("동일 유형 3회차", "미병합 고립 4회차"). 그 결과 **문서마다 회차가 다르다** —
`docs/reviews/recurring_failure_taxonomy_2026-09-20.md` §2.7이 실측한 것이 그
불일치다(병렬 중복 구현은 CLAUDE.md가 2회차, MEMORY 09-01이 6회차, 실제 발생은
7회로 서로 다른 숫자를 말한다). 회차를 셀 수 없으면 "2회차부터 코드로 막는다"는
규칙도 집행할 수 없다.

그래서 사고를 **데이터**로 둔다. 계수는 산문이 아니라 `compute_nth`가 한다.

설계 원칙 3가지
---------------
1. **모른다 ≠ 1회차** — `series_id`가 비어 있으면 `nth`는 `None`이다. 0도 1도
   아니다. 계열 미배정을 "첫 발생"으로 접으면 2회차 강제가 통째로 무력해진다
   (CLAUDE.md "모른다 ≠ 아니다" — 3상태를 truthiness로 접지 않는다).
2. **원문 보존** — 시드의 회차 문자열은 `series_raw`에 그대로 남긴다. `series_id`는
   그것을 키워드 표로 정규화한 *파생값*이며 `series_source`가 출처를 말한다.
   추정을 원문으로 덮지 않는다(CLAUDE.md "추정 금지").
3. **손편집 금지** — 스키마 검사는 `validate`가 하고, 등재는 CLI가 한다. 대장을
   직접 고치는 경로는 이 저장소에서 이미 사고를 냈다(YAML 손편집·백틱 소실).

저장 형식: `backlog/incidents.ndjson` (한 줄 = 사고 1건).
YAML이 아니라 NDJSON인 이유는 셋이다 — ① 676행 매핑을 YAML로 두면 인용 규칙
(백틱·콜론·따옴표)이 사고 표면이 된다(2026-09-08 백틱 치환 소실이 정확히 그 부류다)
② 한 줄 = 한 레코드라 append가 충돌을 안 만든다 ③ 시드 원천이 이미 JSON Lines다.

의존성: 표준 라이브러리만. `scripts/harness/`의 다른 모듈과 같은 계약이다
(루트에 파이썬 프로젝트가 없어 어떤 환경에서도 `python3` 단독 임포트 가능해야 한다).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dc_fields
from pathlib import Path

# ── 폐쇄 집합 (정의 정본 = docs/data/recurring_failure_ledger_2026-09-20/schema.md) ──

CATS: tuple[str, ...] = tuple("ABCDEFGHIJK")

CAT_TITLES: dict[str, str] = {
    "A": "검증 판정 무효화",
    "B": "보호 장치 자기위장",
    "C": "미머지 고립·병렬 충돌",
    "D": "부재·존재 오판",
    "E": "Kiki 런북·안내 결함",
    "F": "인코딩·플랫폼",
    "G": "대장·하네스 조작 결함",
    "H": "관측·측정 도구 결함",
    "I": "외부 의존성·SDK 표면",
    "J": "알고리즘 무작동·정상 응답 오인",
    "K": "기타·설계 판단",
}

DAMAGE_CLASSES: tuple[str, ...] = (
    "none",
    "wasted_round",
    "discarded_work",
    "ci_red",
    "latent_days",
    "false_pass",
    "data_loss",
)

FIX_FORMS: tuple[str, ...] = (
    "rule",
    "code",
    "task",
    "rule+code",
    "rule+task",
    "none",
    "unknown",
)

# 대책이 *상환*으로 계상되는 형태 — 산문(rule)만으로는 상환이 아니다.
# `none`·`unknown`도 상환이 아니다: 2회차 강제가 막으려는 것은 "대책 없음"이고,
# 대책을 안 적은 것과 산문만 적은 것은 집행 지점이 없다는 점에서 같다.
SETTLING_FIX_FORMS: frozenset[str] = frozenset({"code", "task", "rule+code", "rule+task"})

WHO_CAUGHT: tuple[str, ...] = ("self", "kiki", "bot", "ci", "luck", "unknown")

SERIES_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

LEDGER_NAME = "incidents.ndjson"

# 시드 회차 문자열 → 계열 슬러그. **키워드 표이지 추론이 아니다** — 각 항목은
# 시드의 `series` 원문에 실제로 등장하는 부분 문자열이며, 원문은 `series_raw`에
# 그대로 남는다. 매칭은 위에서부터 첫 일치(순서가 의미를 갖는다).
#
# 여기 없는 회차 문자열(예: "반복 실수 9회차")은 **일부러** 미배정으로 둔다.
# 그 표기는 특정 유형이 아니라 MEMORY의 통산 카운터라 계열 키가 될 수 없다 —
# 서로 다른 사고에 같은 번호가 붙는다. 억지로 묶으면 회차가 거짓이 된다.
SERIES_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("미병합 고립", "unmerged-isolation"),
    ("미머지 고립", "unmerged-isolation"),
    ("정본화≠집행", "canon-vs-enforcement"),
    ("선언≠배선", "declared-unwired"),
    ("도구 결함", "measurement-tool-defect"),
    ("cp949", "encoding-cp949"),
    ("검증 장치 미배선", "verification-device-unwired"),
    ("검증 장치 배선", "verification-device-unwired"),
    ("변별력 없는 검증 스텝", "nondiscriminating-check"),
    ("ARCH-13·OPS-15", "task-id-collision"),
    ("ID 충돌", "task-id-collision"),
    ("정정 경로 부재로 인한 번호 소모", "task-id-collision"),
    ("HARN-10/HARN-15", "task-id-collision"),
    ("OPS-07", "parallel-duplicate-implementation"),
    ("병렬 중복", "parallel-duplicate-implementation"),
    ("병렬 세션 중복", "parallel-duplicate-implementation"),
    ("픽스처", "fixture-clause-untouched"),
    ("붙여넣기 실행", "paste-block-execution"),
    ("만료 없는", "unexpiring-grandfather"),
    ("fail-open", "always-failing-fail-open"),
    ("stray-code", "stray-code-audit"),
    ("부분 스위트 통과", "partial-suite-pass"),
    ("측정 회차 공전", "measurement-round-spin"),
    ("부재 오독", "absence-misjudgement"),
    ("회수 재대조", "recovery-acceptance-recheck"),
    ("셸 이스케이프", "shell-escape-loss"),
)


def series_id_from_raw(raw: str) -> str:
    """시드 회차 문자열 → 계열 슬러그(모르면 빈 문자열). 순수 함수."""
    text = (raw or "").strip()
    if not text:
        return ""
    for needle, slug in SERIES_KEYWORDS:
        if needle in text:
            return slug
    return ""


# ── 레코드 ───────────────────────────────────────────────────────────────────


@dataclass
class Incident:
    """사고 1건 = `backlog/incidents.ndjson` 1줄.

    `nth`는 **필드가 아니다** — `compute_nth`가 대장 전체에서 계산한다. 저장하면
    두 진실 원천이 생기고, 과거 사고가 뒤늦게 등재될 때 조용히 어긋난다.
    """

    date: str
    cat: str
    title: str
    sub: str = ""
    cause: str = ""
    damage: str = "0"
    damage_class: str = "none"
    fix_form: str = "unknown"
    fix_ref: str = ""
    series_id: str = ""
    who_caught: str = "unknown"
    quote: str = ""
    src: str = ""
    line: int | None = None
    # 시드 원문 보존 — 파생된 series_id가 틀려도 근거를 되짚을 수 있다.
    series_raw: str = ""
    series_source: str = ""  # "" | seed_keyword | manual
    reviewed: bool = False

    def validate(self) -> list[str]:
        """스키마 위반 목록 (빈 리스트 = 정상)."""
        errors: list[str] = []
        tag = f"{self.date}/{self.title[:24]}"
        if not DATE_RE.match(self.date or ""):
            errors.append(f"{tag}: date는 YYYY-MM-DD 형식이어야 함 (받은 값 {self.date!r})")
        if self.cat not in CATS:
            errors.append(f"{tag}: cat '{self.cat}' 미등록 (A~K)")
        if not (self.title or "").strip():
            errors.append(f"{tag}: title 누락")
        if self.damage_class not in DAMAGE_CLASSES:
            errors.append(f"{tag}: damage_class '{self.damage_class}' 미등록")
        if self.fix_form not in FIX_FORMS:
            errors.append(f"{tag}: fix_form '{self.fix_form}' 미등록")
        if self.who_caught not in WHO_CAUGHT:
            errors.append(f"{tag}: who_caught '{self.who_caught}' 미등록")
        if self.series_id and not SERIES_ID_RE.match(self.series_id):
            errors.append(f"{tag}: series_id '{self.series_id}' 형식 위반 (소문자 kebab)")
        if self.line is not None and (not isinstance(self.line, int) or self.line < 0):
            errors.append(f"{tag}: line은 0 이상 정수 또는 null (받은 값 {self.line!r})")
        if not isinstance(self.reviewed, bool):
            errors.append(f"{tag}: reviewed는 bool이어야 함 (받은 값 {self.reviewed!r})")
        return errors


_FIELD_NAMES = tuple(f.name for f in dc_fields(Incident))


def from_dict(data: dict, *, source: str = "") -> tuple[Incident | None, list[str]]:
    """dict → Incident. 미등록 키는 **오류**다(오타가 조용히 사라지지 않게)."""
    unknown = sorted(set(data) - set(_FIELD_NAMES))
    if unknown:
        return None, [f"{source}: 미등록 필드 {unknown}"]
    missing = [k for k in ("date", "cat", "title") if k not in data]
    if missing:
        return None, [f"{source}: 필수 필드 누락 {missing}"]
    return Incident(**data), []


def to_line(incident: Incident) -> str:
    """NDJSON 1줄 — 키 순서는 dataclass 선언 순서로 고정(diff 안정)."""
    return json.dumps(asdict(incident), ensure_ascii=False, sort_keys=False)


# ── 저장소 I/O ───────────────────────────────────────────────────────────────


def ledger_path(root: Path) -> Path:
    return root / "backlog" / LEDGER_NAME


def load_incidents(root: Path) -> tuple[list[Incident], list[str]]:
    """대장 읽기 — (레코드, 스키마 오류). 파일 부재는 빈 대장(오류 아님)."""
    path = ledger_path(root)
    if not path.exists():
        return [], []
    incidents: list[Incident] = []
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
            errors.append(f"{where}: 객체가 아님 (받은 타입 {type(data).__name__})")
            continue
        incident, field_errors = from_dict(data, source=where)
        if incident is None:
            errors.extend(field_errors)
            continue
        schema_errors = incident.validate()
        errors.extend(f"{where} {e}" for e in schema_errors)
        incidents.append(incident)
    return incidents, errors


def save_incidents(root: Path, incidents: list[Incident]) -> Path:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(to_line(i) + "\n" for i in incidents)
    path.write_text(body, encoding="utf-8")
    return path


# ── 회차 계산 ────────────────────────────────────────────────────────────────


def compute_nth(incidents: list[Incident]) -> list[int | None]:
    """각 레코드의 회차 — 같은 `series_id` 안에서 (date, 파일 위치) 순 1-기반 서수.

    `series_id`가 비면 `None`(미배정 = 모른다). 파일 순서에 의존하지 않도록 날짜로
    정렬하므로, 과거 사고를 뒤늦게 append해도 회차가 올바르게 재계산된다.
    """
    order: dict[str, list[int]] = {}
    for index, incident in enumerate(incidents):
        if incident.series_id:
            order.setdefault(incident.series_id, []).append(index)
    result: list[int | None] = [None] * len(incidents)
    for indices in order.values():
        for rank, index in enumerate(sorted(indices, key=lambda i: (incidents[i].date, i)), 1):
            result[index] = rank
    return result


def next_nth(incidents: list[Incident], candidate: Incident) -> int | None:
    """`candidate`를 대장에 넣었을 때의 회차. 미배정이면 None."""
    if not candidate.series_id:
        return None
    nths = compute_nth([*incidents, candidate])
    return nths[-1]


def repeat_settlement_error(incidents: list[Incident], candidate: Incident) -> str | None:
    """② 2회차 코드 착지 강제 — 위반이면 사유 문자열, 정상이면 None.

    같은 계열의 2회차 이상인데 대책이 산문(rule)뿐이거나 아예 없으면(none/unknown)
    거부한다. 이 저장소가 반복해 배운 것은 "산문 규칙은 집행 지점이 없어 막고 있는지
    검증할 수 없다"이고(보고서 §2.6 — 규칙 52건 중 산문만 56%), 그 학습을 등재
    시점에 기계가 강제하는 자리가 여기다.

    `fix_ref`도 함께 요구한다 — acceptance가 말하는 "code 또는 task **참조**"의
    참조가 그것이다. 형태만 code라고 적고 어느 테스트·어느 태스크인지 비어 있으면
    다음 세션이 그 대책을 찾을 수 없다.
    """
    nth = next_nth(incidents, candidate)
    if nth is None or nth < 2:
        return None
    series = candidate.series_id
    if candidate.fix_form not in SETTLING_FIX_FORMS:
        return (
            f"계열 '{series}' {nth}회차인데 fix_form='{candidate.fix_form}' — "
            f"2회차부터는 코드 또는 태스크 상환이 필요하다. "
            f"허용: {sorted(SETTLING_FIX_FORMS)} "
            f"(--fix-form code --fix-ref <테스트 파일 경로 또는 HARN/OPS 태스크 ID>)"
        )
    if not candidate.fix_ref.strip():
        return (
            f"계열 '{series}' {nth}회차인데 fix_ref가 비어 있다 — "
            f"fix_form='{candidate.fix_form}'의 실제 착지 지점"
            f"(테스트 파일 경로 또는 HARN/OPS 태스크 ID)을 --fix-ref로 지정하라"
        )
    return None


# ── 집계 ─────────────────────────────────────────────────────────────────────


@dataclass
class SeriesRow:
    series_id: str
    count: int
    max_nth: int
    first_date: str
    last_date: str
    settled: bool  # 계열 안에 code/task 상환이 1건이라도 있는가
    fix_refs: list[str] = field(default_factory=list)


@dataclass
class Report:
    """`incident report`의 산출물 — 표 5종 + 분모."""

    total: int
    by_cat: dict[str, int]
    by_month: dict[str, int]
    by_damage: dict[str, int]
    by_fix_form: dict[str, int]
    series: list[SeriesRow]
    unassigned_series: int

    @property
    def max_series_nth(self) -> int:
        """계열 최대 회차 — 미배정만 있으면 0(1이 아니다: 센 적이 없다는 뜻)."""
        return max((row.max_nth for row in self.series), default=0)

    @property
    def rule_only_ratio(self) -> float:
        """산문만 대책 비율 — 분모는 전건. 0건이면 0.0."""
        if not self.total:
            return 0.0
        return self.by_fix_form.get("rule", 0) / self.total

    def to_json(self) -> dict:
        return {
            "total": self.total,
            "by_cat": self.by_cat,
            "by_month": self.by_month,
            "by_damage": self.by_damage,
            "by_fix_form": self.by_fix_form,
            "series": [asdict(row) for row in self.series],
            "unassigned_series": self.unassigned_series,
            "max_series_nth": self.max_series_nth,
            "rule_only_ratio": round(self.rule_only_ratio, 4),
        }


def aggregate(incidents: list[Incident]) -> Report:
    """대장 → 표 5종. 순수 함수 — I/O 0."""
    nths = compute_nth(incidents)
    by_cat = Counter(i.cat for i in incidents)
    by_month = Counter(i.date[:7] for i in incidents if DATE_RE.match(i.date or ""))
    by_damage = Counter(i.damage_class for i in incidents)
    by_fix_form = Counter(i.fix_form for i in incidents)

    grouped: dict[str, list[tuple[Incident, int]]] = {}
    for incident, nth in zip(incidents, nths, strict=True):
        if incident.series_id and nth is not None:
            grouped.setdefault(incident.series_id, []).append((incident, nth))

    series: list[SeriesRow] = []
    for series_id, members in grouped.items():
        dates = sorted(m.date for m, _ in members)
        refs = sorted({m.fix_ref for m, _ in members if m.fix_ref.strip()})
        series.append(
            SeriesRow(
                series_id=series_id,
                count=len(members),
                max_nth=max(n for _, n in members),
                first_date=dates[0],
                last_date=dates[-1],
                settled=any(m.fix_form in SETTLING_FIX_FORMS for m, _ in members),
                fix_refs=refs,
            )
        )
    series.sort(key=lambda r: (-r.max_nth, r.series_id))

    return Report(
        total=len(incidents),
        by_cat={c: by_cat.get(c, 0) for c in CATS if by_cat.get(c, 0)},
        by_month=dict(sorted(by_month.items())),
        by_damage={d: by_damage.get(d, 0) for d in DAMAGE_CLASSES if by_damage.get(d, 0)},
        by_fix_form={f: by_fix_form.get(f, 0) for f in FIX_FORMS if by_fix_form.get(f, 0)},
        series=series,
        unassigned_series=sum(1 for n in nths if n is None),
    )


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "—"


def render_report(report: Report) -> str:
    """보고서 §2와 같은 마크다운 표 5종.

    분모(`total`)를 표마다 다시 적는다 — 표 하나만 잘라 인용해도 비율의 근거가
    함께 가도록(CLAUDE.md "도구가 기본값으로 자르는 축" 대비).
    """
    total = report.total
    out: list[str] = [f"# 사고 대장 리포트 — 전체 {total}건", ""]

    out += ["## 대분류", "", "| 코드 | 대분류 | 건수 | 비율 |", "|---|---|---:|---:|"]
    for cat, count in sorted(report.by_cat.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"| {cat} | {CAT_TITLES.get(cat, '?')} | {count} | {_pct(count, total)} |")
    out += [f"| | **합계** | **{sum(report.by_cat.values())}** | 100% |", ""]

    out += ["## 월", "", "| 월 | 사고 |", "|---|---:|"]
    for month, count in report.by_month.items():
        out.append(f"| {month} | {count} |")
    out += [f"| **합계** | **{sum(report.by_month.values())}** |", ""]

    out += ["## 피해 유형", "", "| 피해 유형 | 건수 | 비율 |", "|---|---:|---:|"]
    for name, count in sorted(report.by_damage.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"| {name} | {count} | {_pct(count, total)} |")
    out.append("")

    out += ["## 대책 형태", "", "| 대책 형태 | 건수 | 비율 |", "|---|---:|---:|"]
    for name, count in sorted(report.by_fix_form.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(f"| {name} | {count} | {_pct(count, total)} |")
    out.append("")

    out += [
        "## 계열 최대 회차",
        "",
        "| 계열 | 회차 | 첫 발생 | 최근 | 상환 |",
        "|---|---:|---|---|---|",
    ]
    for row in report.series:
        settled = "code/task" if row.settled else "**산문뿐**"
        out.append(
            f"| {row.series_id} | {row.max_nth} | {row.first_date} | {row.last_date} | {settled} |"
        )
    out += [
        "",
        f"계열 미배정 {report.unassigned_series}건 — 회차를 세지 않는다(모른다 ≠ 1회차). "
        f"배정된 계열의 최대 회차는 {report.max_series_nth}이다.",
        "",
        "판정 범위: 이 표의 회차는 **대장 레코드를 센 것**이다. "
        "`recurring_failure_taxonomy_2026-09-20.md` §2.7의 회차는 *문서가 스스로 센 것*이라 "
        "같은 계열에서도 숫자가 다를 수 있다 — 그 불일치가 이 대장을 만든 이유이므로 "
        "여기서 맞추지 않는다(한쪽을 다른 쪽에 맞추면 어느 쪽이 실측인지 알 수 없게 된다).",
        "",
    ]
    return "\n".join(out)


# ── 시드 ─────────────────────────────────────────────────────────────────────

# 시드 원천의 키 중 대장 스키마로 옮기지 않는 것 — 추출 파이프라인의 중간 산물이다.
_SEED_DROP_KEYS = frozenset({"_dups"})


def seed_from_jsonl(path: Path) -> tuple[list[Incident], list[str]]:
    """추출 산출물(JSON Lines) → 대장 레코드. (레코드, 오류)."""
    incidents: list[Incident] = []
    errors: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        where = f"{path.name}:{lineno}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: JSON 파싱 실패 — {type(exc).__name__}: {exc}")
            continue
        data = {k: v for k, v in data.items() if k not in _SEED_DROP_KEYS}
        series_raw = str(data.pop("series", "") or "")
        series_id = series_id_from_raw(series_raw)
        data["series_raw"] = series_raw
        data["series_id"] = series_id
        data["series_source"] = "seed_keyword" if series_id else ""
        data["reviewed"] = False  # 사람 검수 전 — acceptance ③
        incident, field_errors = from_dict(data, source=where)
        if incident is None:
            errors.extend(field_errors)
            continue
        errors.extend(f"{where} {e}" for e in incident.validate())
        incidents.append(incident)
    incidents.sort(key=lambda i: i.date)
    return incidents, errors
