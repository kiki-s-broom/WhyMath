"""EOS Core 불투명 페이로드 해석 게이트 — 과목 중립성의 **반증 가능한** 검사 (ARCH-43).

## 왜 이 검사가 필요한가

Subject Contract v1(`schema/subject_adapter.py`)의 15필드 중 13개가 `str`·`str | None`·
`tuple[str, ...]`라 **어떤 과목의 어떤 값이든 받는다**. 그래서 "Physics로 필드를 채워 본다"는
검사(EOS-92 갈래 A)는 실패 사례를 구성할 수 없고, 성공/실패 양쪽에서 같은 값을 낸다 — 검증이
아니라 위장이다(CLAUDE.md "변별력 없는 검증 스텝 금지"). 계약 파일 자신이 이 함정을 예고했다:
*"Core 코드가 `answer_kind` 값을 읽어 분기하기 시작하는 것은 필드 개수가 안 변하므로 CI가
초록이다. 그런데 과목 중립성이 실제로 깨지는 주된 경로가 바로 이쪽이다."*

이 스크립트는 그 축 — **Core가 불투명 페이로드를 해석하는가** — 을 정적으로 잡는 게이트다.

## 위반 정의 (먼저 정의하고, 실제로 주입해 RED를 확인한 뒤에만 검사로 친다)

> **CORE 배정 모듈**이 계약이 *불투명*이라고 선언한 필드(`answer`·`answer_kind`·`conditions` —
> 계약 docstring "불투명 페이로드 원칙" 절에서 기계로 파생)의 **값**을 읽어 아래 자리에 놓으면
> 위반이다. Core는 그 값을 *들고 있거나 넘길 수는* 있지만 *읽어서 뜻을 정하면* 안 된다.

| 종류 | 형태 | 예 |
|---|---|---|
| `eq_literal` | 리터럴·명명 상수와 `==`/`!=` | `p.answer_kind == "quadratic"` · `kind != KIND_X` |
| `membership` | 어휘 집합에 `in`/`not in` | `p.answer_kind in ("a", "b")` · `kind not in KINDS` |
| `substring_probe` | 값 *안*을 `in`으로 더듬기 | `"=" in p.conditions` |
| `dict_key` | 값을 조회 키로 사용 | `HANDLERS[p.answer_kind]` · `TABLE.get(p.answer_kind)` |
| `match` | 값을 `match` 대상으로 사용 | `match p.answer_kind: case "x": …` |
| `str_parse` | 값을 문자열 메서드로 파싱 | `p.conditions.split(";")` · `kind.startswith("ph")` |

값을 **읽는 형태** 4종을 모두 같은 값으로 본다 — 표기를 바꿔 빠져나가지 못하게 하기 위해서다
(CLAUDE.md 2026-09-01 ①: 금지 패턴 문자열 열거가 아니라 **구성된 결과(AST)** 검사):
`x.answer_kind`(속성) · `x["answer_kind"]`(첨자) · `x.get("answer_kind")`(dict 조회) ·
`k = x.answer_kind; …k…`(같은 스코프의 **별칭** — 한 단계) · `x.answer_kind.strip()`(값을 보존하는
str 메서드 경유). `l1.problem_bank.populate`의 실제 위반이 정확히 별칭 경유 형태다
(`kind_raw = verify_raw.get("answer_kind")` → `kind_raw in (...)`) — 별칭을 안 보면 이 스캐너는
실재하는 유일한 위반을 놓친 채 0을 낸다.

**의도적으로 위반이 아닌 것** (구조적 취급이지 해석이 아니다):
- 두 불투명 값끼리의 비교 `a.answer_kind == b.answer_kind` — Core는 뜻을 모른 채 같음만 본다
- 진위 검사 `if p.conditions:` · `is None` — 존재 여부이지 내용이 아니다
- 인자로 넘김 `f(p.answer_kind)` · 순회 `for c in p.conditions` · 그대로 담기 `d.k = p.answer_kind`
- 소문자 이름과의 `==`(`kind == expected`) — 어휘를 여는 쪽은 상수(대문자)·리터럴이며, 그 외는
  판단할 수 없어 세지 않는다(정직한 공백 — 아래 "한계" 참조)

## 예외(스캔 대상 아님) — 새 목록을 만들지 않는다

Core의 정의는 `eos_core_adapter_boundary_scan.py`의 `BOUNDARY_MAP`/`classify`(경계 배정 정본)를
그대로 가져온다. `CORE`만 스캔하고 `ADAPTER`(해석하는 쪽이 정상 — `l4.subject_adapter_math`·
`l3.verify_*` 등)·`MIXED`(파일 단위로 못 가르는 것)·`INFRA`(횡단·하네스)는 분모에서 뺀다.
따라서 이 게이트의 0은 EOS-84 프로브와 같은 뜻의 **"CORE 배정 모듈 기준의 0"**이다.

## 기존 장치로 되지 않는 이유 (acceptance ③ — 확장 대신 자매 스크립트인 사유)

- `eos_core_adapter_boundary_scan.py` — 정적 **import** 간선만 본다(계약 파일 자인). 페이로드 해석은
  import 없이 일어난다.
- `eos_core_boundary_probe.py`의 `scan_literal_compares` — 비교문의 **리터럴이 수학 어휘인지**
  (`"quadratic"`·`"math"`)를 본다. `if p.answer_kind == "physics.quantity_with_unit"`처럼 어휘 목록
  밖의 값은 통과한다. 그쪽은 *어떤 리터럴인가*, 이쪽은 *무엇을 읽는가*가 키다 — 직교한다.
- 둘 다 **계측기**(위반 수로 exit 1을 내지 않는다는 계약)라 게이트 의미론을 그 안에 넣으면 계약이
  깨진다. EOS-84가 boundary_scan을 확장하지 않고 자매를 둔 것과 같은 판단이다.

## 종료코드 (판정은 exit code로 — 출력 문자열이 아니다)

- `0` — 위반이 기준선(`KNOWN_VIOLATIONS`)과 **지문 단위로** 정확히 일치(현행 1건은 EOS-85가 소유)
- `1` — 기준선에 없는 지문의 위반이 생겼다 · **또는** 기준선의 지문이 사라졌다(ratchet — 기준선을
  줄여라)

기준선의 정체성은 **(모듈, 종류)별 개수가 아니라 위반 하나하나의 지문**이다 — 지문 =
`sha256(모듈|종류|해석 식의 ast.unparse)[:12]`. 개수만 대조하면 "알려진 위반을 갚으면서 같은 모듈에
새 위반을 하나 넣는" 변경이 1→1로 상쇄돼 통과한다(PR #1014 Codex P1). 줄 번호는 정체성이 아니다 —
위 코드가 밀리면 줄은 바뀌지만 지문은 그대로이고, 식이 바뀌면(어휘 추가 등) 지문이 바뀌어 다시
승인을 받아야 한다. 지문은 `--json` 산출과 마크다운 표에 함께 나온다(기준선에 옮겨 적는 값).
- `2` — **측정 실패**: 스캔 대상 CORE 모듈 0건 · 파일 읽기/파싱 실패 · 계약에서 불투명 필드 파생
  실패. 측정 실패를 "위반 없음"으로 위장하지 않는다(CLAUDE.md 2026-09-01 ④ "스캔 0건은 실패")

## 한계 (있는 척 금지)

- **이름 기반**이다 — 타입을 풀지 않으므로 같은 이름의 다른 필드(`RightsEntity.conditions` 등)도
  같은 규칙으로 본다. 실측상 CORE에서 그런 자리는 해석 위치에 없어 오탐 0이지만, 생기면 기준선에
  소유자·재확인 지점과 함께 적어야 한다(만료 없는 유예 금지).
- 별칭은 **한 단계·같은 스코프**만 본다. `k = f(p.answer_kind)`처럼 함수를 지나면 놓친다.
- 소문자 이름과의 `==`는 세지 않는다 — 어휘를 변수로 들여오면 놓친다.
- 동적 접근(`getattr(p, "answer_kind")`)·문자열 포맷 뒤 파싱은 못 본다.
- 정적이다 — 런타임에 값을 해석하는 LLM 프롬프트 조립 등은 이 축이 아니다.

## 집행 지점 (정본화 ≠ 집행)

`tests/infra/test_eos_opaque_payload_gate.py`가 (a) 실 저장소 스캔을 기준선과 대조하고 (b) 위반
6종을 합성 소스로 **주입해 RED**를 확인하며 (c) ADAPTER 배정에서의 같은 패턴은 초록임을, (d) 0건·
파싱 실패가 exit 2임을 고정한다. 그 파일은 CI `infra-contracts` 잡(`python3 -m pytest tests/infra`)
에서 돈다. 실 저장소와 합성 주입은 **같은 판정 함수**(`scan_source`·`run_gate`·`evaluate`)를 쓴다.

사용법:
    python3 scripts/analysis/eos_opaque_payload_gate.py            # 마크다운 리포트(stdout) + exit
    python3 scripts/analysis/eos_opaque_payload_gate.py --json out.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterator

HERE = pathlib.Path(__file__).resolve()
REPO = HERE.parents[2]
BOUNDARY_SCAN_SCRIPT = HERE.with_name("eos_core_adapter_boundary_scan.py")
DEFAULT_CONTRACT = REPO / "src" / "backend" / "whymath_backend" / "schema" / "subject_adapter.py"

# 계약 docstring에서 불투명 필드를 파생할 절 제목 — 계약 파일의 *기존 규칙*을 그대로 읽는다.
OPAQUE_SECTION_HEADING = "## 불투명 페이로드 원칙"
OPAQUE_DTO_CLASS = "ProblemStatement"

# 값을 **보존**하는 str 메서드 — 경유해도 여전히 같은 불투명 값이다(별칭 전파).
STR_PASSTHROUGH: frozenset[str] = frozenset(
    {"strip", "lstrip", "rstrip", "lower", "upper", "casefold", "title", "swapcase", "replace"}
)
# 값을 **파싱**하는 str 메서드 — Core가 페이로드의 내부 구조를 읽는 자리다.
STR_PARSE: frozenset[str] = frozenset(
    {
        "split",
        "rsplit",
        "splitlines",
        "partition",
        "rpartition",
        "startswith",
        "endswith",
        "find",
        "rfind",
        "index",
        "rindex",
        "removeprefix",
        "removesuffix",
        "count",
    }
)

VIOLATION_KINDS: tuple[str, ...] = (
    "eq_literal",
    "membership",
    "substring_probe",
    "dict_key",
    "match",
    "str_parse",
)


class ContractDerivationError(RuntimeError):
    """계약 파일에서 불투명 필드를 파생하지 못했다 — 측정 실패(exit 2)이지 '위반 없음'이 아니다."""


@dataclass(frozen=True)
class Grandfathered:
    """기준선 항목 — 소유자와 재확인 지점이 없는 유예는 만료 없는 유예다(금지).

    `fingerprints`는 유예하는 위반 **하나하나**의 지문(`fingerprint_of`)이다 — 개수가 아니라 정체성.
    같은 지문이 두 자리에 있으면(동일 식이 두 번) 그 지문을 두 번 적는다.
    """

    fingerprints: tuple[str, ...]
    owner: str
    recheck: str

    @property
    def count(self) -> int:
        return len(self.fingerprints)


def fingerprint_of(module: str, kind: str, expr: str) -> str:
    """위반의 안정 지문 — 줄 번호와 무관, 해석 식(`ast.unparse`)이 바뀌면 바뀐다."""
    digest = hashlib.sha256(f"{module}|{kind}|{expr}".encode("utf-8")).hexdigest()
    return digest[:12]


# 기준선 — (CORE 모듈, 위반 종류) → 유예. **줄이는 방향으로만** 고친다.
# **비어 있다 — EOS-85 착지로 유일 항목이 상환됐다**(2026-09-06 · 판정 기준 main dc2e6583).
# 종전 항목: `("l1.problem_bank.populate", "membership")` 지문 `d93b2c7770a0` —
# `_verify_meta_from_raw`의 `kind_raw = verify_raw.get("answer_kind")` → `kind_raw in (17종)`.
# 그 항목의 `recheck`가 "EOS-85 착지 시 이 항목을 비운다"였고, 실제로 그렇게 했다(유예는
# 만료 지점을 동반해야 한다는 규칙이 지켜진 사례 — 만료가 없었으면 이 줄은 남았을 것이다).
# 상환 형태는 어휘의 *이관*이 아니라 *제거*다: 적재기는 이제 answer_kind를 읽어 해석하지 않고
# 형식만 보고 통과시킨다(판정 권위는 L3 `acceptance._CONCEPTUAL_VERIFIERS`).
KNOWN_VIOLATIONS: dict[tuple[str, str], Grandfathered] = {}


@dataclass(frozen=True)
class Hit:
    lineno: int
    kind: str
    snippet: str  # 사람용 100자 절단
    expr: str  # 지문 재료 — 해석 식의 ast.unparse 전문


@dataclass(frozen=True)
class Violation:
    module: str
    path: str
    lineno: int
    kind: str
    snippet: str
    fingerprint: str  # 기준선 대조 키 — 줄 번호가 아니라 이것이 정체성이다


@dataclass
class GateResult:
    opaque_fields: tuple[str, ...]
    files_total: int
    scanned: int  # CORE 모듈 수 = 분모
    skipped: dict[str, int]  # 배정별 제외 모듈 수
    violations: list[Violation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 읽기·파싱 실패(타입명 포함)


# ──────────────────────────────────────────────────────────────────────
# 경계 배정 정본 재사용 — 새 목록을 만들지 않는다
# ──────────────────────────────────────────────────────────────────────
def load_boundary_scan() -> Any:
    """`eos_core_adapter_boundary_scan.py`를 로드해 `classify`·`module_name`·`DEFAULT_SOURCE` 사용.

    `@dataclass`가 어노테이션을 풀 때 sys.modules에서 자기 모듈을 찾으므로 등록 후 실행한다
    (선례: `tests/infra/test_eos_boundary_contract_wiring.py`).
    """
    name = "_eos_boundary_scan_for_opaque_gate"
    spec = importlib.util.spec_from_file_location(name, BOUNDARY_SCAN_SCRIPT)
    if spec is None or spec.loader is None:
        raise ContractDerivationError(f"경계 배정 정본 로드 불가: {BOUNDARY_SCAN_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


# ──────────────────────────────────────────────────────────────────────
# 불투명 필드 — 계약 docstring의 기존 규칙에서 파생
# ──────────────────────────────────────────────────────────────────────
_BACKTICK_IDENT = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def opaque_fields_from_contract(contract_source: str) -> frozenset[str]:
    """계약 모듈 docstring의 "불투명 페이로드 원칙" 절이 이름 붙인 `ProblemStatement` 필드.

    이중 진실 원천을 만들지 않으려고 **여기서 목록을 손으로 적지 않는다** — 계약이 스스로 불투명
    하다고 선언한 필드만 쓴다. 절이 없거나 결과가 비면 측정 실패다(공허 통과 금지).
    """
    tree = ast.parse(contract_source)
    doc = ast.get_docstring(tree) or ""
    lines = doc.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == OPAQUE_SECTION_HEADING)
    except StopIteration as exc:
        raise ContractDerivationError(
            f"계약 docstring에 {OPAQUE_SECTION_HEADING!r} 절이 없다 — 불투명 필드를 파생할 수 없다"
        ) from exc
    section: list[str] = []
    for ln in lines[start + 1 :]:
        if ln.startswith("## "):
            break
        section.append(ln)
    named = set(_BACKTICK_IDENT.findall("\n".join(section)))

    dto_fields: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == OPAQUE_DTO_CLASS:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    dto_fields.add(stmt.target.id)
    if not dto_fields:
        raise ContractDerivationError(f"계약에 {OPAQUE_DTO_CLASS} 필드 선언이 없다")
    result = frozenset(named & dto_fields)
    if not result:
        raise ContractDerivationError(
            f"{OPAQUE_SECTION_HEADING} 절이 {OPAQUE_DTO_CLASS} 필드를 하나도 이름 붙이지 않는다: "
            f"절 식별자={sorted(named)} · 필드={sorted(dto_fields)}"
        )
    return result


# ──────────────────────────────────────────────────────────────────────
# 판정 함수 — 실 저장소와 합성 주입이 **같은 함수**를 쓴다
# ──────────────────────────────────────────────────────────────────────
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _iter_scope(root: ast.AST) -> Iterator[ast.AST]:
    """root 스코프의 노드를 소스 순서로 순회 — 중첩 스코프(def/class/lambda) 내부는 건너뛴다."""
    for child in ast.iter_child_nodes(root):
        yield child
        if isinstance(child, _SCOPE_NODES):
            continue
        yield from _iter_scope(child)


def _is_upper_name(node: ast.expr) -> bool:
    """`KIND_X`·`Kind.X` — 어휘를 여는 명명 상수(대문자 시작 관용구)."""
    if isinstance(node, ast.Name):
        return node.id[:1].isupper()
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and node.value.id[:1].isupper()
    return False


def _is_str_const(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _str_value(node: ast.expr) -> str | None:
    """문자열 리터럴이면 그 값, 아니면 None — `in fields` 대조용(None은 어떤 필드명도 아니다)."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Judge:
    """불투명 값 읽기 4형태 + 별칭을 한 값으로 보고, 해석 위치 6종을 판정한다."""

    def __init__(self, fields: frozenset[str]) -> None:
        self.fields = fields
        self.hits: list[Hit] = []

    # ── 값 읽기 ──
    def is_opaque(self, node: ast.AST | None, aliases: set[str]) -> bool:
        if isinstance(node, ast.Attribute):
            return node.attr in self.fields
        if isinstance(node, ast.Subscript):
            return _str_value(node.slice) in self.fields
        if isinstance(node, ast.Name):
            return node.id in aliases
        if isinstance(node, ast.NamedExpr):
            return self.is_opaque(node.value, aliases)  # (k := p.answer_kind) == "x"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # x.get("answer_kind") — dict 조회로 읽기
            if node.func.attr == "get" and node.args:
                return _str_value(node.args[0]) in self.fields
            # x.answer_kind.strip() — 값을 보존하는 메서드 경유
            if node.func.attr in STR_PASSTHROUGH:
                return self.is_opaque(node.func.value, aliases)
        return False

    # ── 스코프 처리 ──
    def scan_scope(self, root: ast.AST, inherited: set[str]) -> None:
        aliases = set(inherited)
        nodes = list(_iter_scope(root))
        # 1패스: 별칭 수집(같은 스코프 · 한 단계). 스코프 전체를 먼저 모으므로 재대입 순서는
        # 보지 않는다 — 보수적(놓치는 쪽이 아니라 더 잡는 쪽)이며 docstring "한계"에 명시.
        for n in nodes:
            if isinstance(n, ast.Assign) and self.is_opaque(n.value, aliases):
                aliases.update(t.id for t in n.targets if isinstance(t, ast.Name))
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                if n.value is not None and self.is_opaque(n.value, aliases):
                    aliases.add(n.target.id)
            elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
                if self.is_opaque(n.value, aliases):
                    aliases.add(n.target.id)
        # 2패스: 해석 위치 판정
        for n in nodes:
            self._judge(n, aliases)
        # 중첩 스코프는 바깥 별칭을 물려받는다(클로저)
        for n in nodes:
            if isinstance(n, _SCOPE_NODES):
                self.scan_scope(n, aliases)

    def _hit(self, node: ast.AST, kind: str) -> None:
        expr = ast.unparse(node).replace("\n", " ")
        self.hits.append(Hit(getattr(node, "lineno", 0), kind, expr[:100], expr))

    def _judge(self, n: ast.AST, aliases: set[str]) -> None:
        if isinstance(n, ast.Compare):
            self._judge_compare(n, aliases)
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load):
            if self.is_opaque(n.slice, aliases):
                self._hit(n, "dict_key")
        elif isinstance(n, ast.Match):
            if self.is_opaque(n.subject, aliases):
                self._hit(n, "match")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "get" and n.args and self.is_opaque(n.args[0], aliases):
                self._hit(n, "dict_key")  # TABLE.get(p.answer_kind)
            elif n.func.attr in STR_PARSE and self.is_opaque(n.func.value, aliases):
                self._hit(n, "str_parse")

    def _judge_compare(self, n: ast.Compare, aliases: set[str]) -> None:
        operands: list[ast.expr] = [n.left, *n.comparators]
        for i, op in enumerate(n.ops):
            left, right = operands[i], operands[i + 1]
            l_op, r_op = self.is_opaque(left, aliases), self.is_opaque(right, aliases)
            if l_op and r_op:
                continue  # 불투명 값끼리 — 구조적 같음, 해석이 아니다
            if isinstance(op, (ast.Eq, ast.NotEq)):
                other = right if l_op else left if r_op else None
                if other is not None and (_is_str_const(other) or _is_upper_name(other)):
                    self._hit(n, "eq_literal")
                    return
            elif isinstance(op, (ast.In, ast.NotIn)):
                if l_op:
                    self._hit(n, "membership")  # 값 ∈ 어휘 집합
                    return
                if r_op:
                    self._hit(n, "substring_probe")  # 무엇 ∈ 값(내부 더듬기)
                    return


def scan_source(source: str, fields: frozenset[str], *, filename: str = "<source>") -> list[Hit]:
    """소스 문자열 하나를 판정한다 — **유일한 판정 함수**. SyntaxError는 호출자에게 던진다."""
    tree = ast.parse(source, filename=filename)
    judge = _Judge(fields)
    judge.scan_scope(tree, set())
    return sorted(judge.hits, key=lambda h: (h.lineno, h.kind))


def run_gate(
    source_root: pathlib.Path,
    *,
    contract_path: pathlib.Path = DEFAULT_CONTRACT,
    log: Any = None,
) -> GateResult:
    """source_root 아래 CORE 배정 모듈 전수를 스캔한다. 단계별로 즉시 log에 남긴다."""
    log = log or (lambda _m: None)
    scan_mod = load_boundary_scan()
    fields = opaque_fields_from_contract(contract_path.read_text(encoding="utf-8"))
    log(f"[gate] 불투명 필드(계약 파생) = {sorted(fields)}")

    files = sorted(p for p in source_root.rglob("*.py") if "__pycache__" not in p.parts)
    result = GateResult(
        opaque_fields=tuple(sorted(fields)), files_total=len(files), scanned=0, skipped={}
    )
    log(f"[gate] 파일 {len(files)} · 루트 {source_root}")
    for path in files:
        mod = scan_mod.module_name(path, source_root)
        verdict = scan_mod.classify(mod)[0]
        if verdict != "CORE":
            result.skipped[verdict] = result.skipped.get(verdict, 0) + 1
            continue
        result.scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
            hits = scan_source(text, fields, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            # 침묵 실패 금지 — 예외 타입명을 남기고 계속 스캔한다(측정 실패는 최종 exit 2)
            msg = f"{path.as_posix()}: {type(exc).__name__}: {exc}"
            result.errors.append(msg)
            log(f"[gate][error] {msg}")
            continue
        for h in hits:
            result.violations.append(
                Violation(
                    mod,
                    path.as_posix(),
                    h.lineno,
                    h.kind,
                    h.snippet,
                    fingerprint_of(mod, h.kind, h.expr),
                )
            )
    log(
        f"[gate] 완료 — CORE {result.scanned}/{result.files_total} 스캔 · "
        f"제외 {result.skipped} · 위반 {len(result.violations)} · 오류 {len(result.errors)}"
    )
    return result


def observed_counts(result: GateResult) -> dict[tuple[str, str], int]:
    """(모듈, 종류)별 개수 — 사람용 요약. **판정에는 쓰지 않는다**(상쇄 우회 — 지문 대조 참조)."""
    return dict(Counter((v.module, v.kind) for v in result.violations))


FingerprintKey = tuple[str, str, str]  # (모듈, 종류, 지문)


def observed_fingerprints(result: GateResult) -> Counter[FingerprintKey]:
    return Counter((v.module, v.kind, v.fingerprint) for v in result.violations)


def baseline_fingerprints(
    baseline: dict[tuple[str, str], Grandfathered],
) -> Counter[FingerprintKey]:
    return Counter((mod, kind, fp) for (mod, kind), g in baseline.items() for fp in g.fingerprints)


def _describe(result: GateResult, keys: Counter[FingerprintKey]) -> list[str]:
    """지문 키를 `모듈 종류 지문 @ 경로:행` 문자열로 푼다 — 관측된 것만 위치가 있다."""
    out: list[str] = []
    for mod, kind, fp in sorted(keys):
        where = [f"{v.path}:{v.lineno}" for v in result.violations if v.fingerprint == fp]
        loc = " · ".join(where) if where else "(현재 관측되지 않음)"
        out.append(f"{mod} {kind} {fp} @ {loc}")
    return out


def evaluate(
    result: GateResult,
    baseline: dict[tuple[str, str], Grandfathered] | None = None,
) -> tuple[int, str]:
    """(exit code, 한 줄 사유). 0=기준선 일치 · 1=신규/증가/감소(ratchet) · 2=측정 실패."""
    baseline = KNOWN_VIOLATIONS if baseline is None else baseline
    if result.errors:
        return 2, f"측정 실패 — 읽기/파싱 오류 {len(result.errors)}건 (위반 없음이 아니다)"
    if result.scanned == 0:
        return 2, "측정 실패 — 스캔 대상 CORE 모듈 0건 (공허 통과 금지)"
    # 정체성 = 지문. (모듈, 종류) 개수 대조는 "옛 위반 상환 + 같은 모듈에 새 위반"이 1→1로 상쇄돼
    # 통과하는 구멍이 있다(PR #1014 Codex P1) — Counter 차집합은 양수만 남기므로 방향별로 따로 본다.
    observed = observed_fingerprints(result)
    expected = baseline_fingerprints(baseline)
    grown = (
        observed - expected
    )  # 기준선에 없는 지문(신규 자리 · 식이 바뀐 옛 자리 · 같은 지문 증가)
    if grown:
        return 1, "기준선 밖의 불투명 페이로드 해석 위반(지문 불일치): " + "; ".join(
            _describe(result, grown)
        )
    shrunk = expected - observed  # 기준선에는 있는데 관측되지 않는 지문(갚은 빚)
    if shrunk:
        return 1, "RATCHET — 기준선의 위반이 사라졌다, KNOWN_VIOLATIONS를 줄여라: " + "; ".join(
            _describe(result, shrunk)
        )
    return (
        0,
        f"위반 {len(result.violations)}건 = 기준선(지문 일치) (CORE {result.scanned}모듈 스캔)",
    )


def render_markdown(result: GateResult, code: int, reason: str) -> str:
    lines = [
        "# EOS Core 불투명 페이로드 해석 게이트 (ARCH-43 · 기계 생성)",
        "",
        f"- 불투명 필드(계약 파생): `{'`·`'.join(result.opaque_fields)}`",
        f"- 분모: CORE **{result.scanned}** 모듈 스캔 / 전체 {result.files_total} 파일 · "
        f"제외 {', '.join(f'{k} {v}' for k, v in sorted(result.skipped.items())) or '없음'}",
        f"- 판정: **exit {code}** — {reason}",
        "",
        f"## 위반 {len(result.violations)}건",
        "",
    ]
    if result.violations:
        lines += ["| 모듈 | 위치 | 종류 | 지문 | 코드 |", "|---|---|---|---|---|"]
        for v in result.violations:
            lines.append(
                f"| `{v.module}` | {v.path}:{v.lineno} | `{v.kind}` | `{v.fingerprint}` "
                f"| `{v.snippet}` |"
            )
    else:
        lines.append(
            "없음 — 단 이는 CORE 배정 모듈 기준·정적·이름 기반의 0이다(모듈 docstring 한계)."
        )
    lines += ["", "## 기준선 (KNOWN_VIOLATIONS)", ""]
    for (mod, kind), g in KNOWN_VIOLATIONS.items():
        fps = "`·`".join(g.fingerprints)
        lines.append(
            f"- `{mod}` `{kind}` ×{g.count} 지문 `{fps}` — 소유 {g.owner} · 재확인 {g.recheck}"
        )
    lines += ["", f"## 측정 오류 {len(result.errors)}건", ""]
    lines += [f"- `{e}`" for e in result.errors] or ["- 없음"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EOS Core 불투명 페이로드 해석 게이트 (ARCH-43)")
    parser.add_argument("--source", type=pathlib.Path, default=None)
    parser.add_argument("--contract", type=pathlib.Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        source = args.source
        if source is None:
            source = REPO / load_boundary_scan().DEFAULT_SOURCE
        if not source.is_dir():
            log(f"[fatal] 소스 루트 없음: {source} (cwd={pathlib.Path.cwd()})")
            return 2
        result = run_gate(source, contract_path=args.contract, log=log)
    except Exception as exc:  # noqa: BLE001 — 최상위 게이트: 원인 타입을 남기고 측정 실패로 끝낸다
        log(f"[fatal] 측정 실패 {type(exc).__name__}: {exc}")
        return 2

    code, reason = evaluate(result)
    print(render_markdown(result, code, reason))
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "exit": code,
                    "reason": reason,
                    "opaque_fields": list(result.opaque_fields),
                    "scanned": result.scanned,
                    "files_total": result.files_total,
                    "skipped": result.skipped,
                    "violations": [vars(v) for v in result.violations],
                    "errors": result.errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"[out] json → {args.json}")
    log(f"[gate] exit {code} — {reason}")
    return code


# ──────────────────────────────────────────────────────────────────────
# 축 (c) 보조 — 계약 시그니처의 식별자 열거 (어휘 판정은 프로브의 `_identifier_is_math`가 단일 원천)
# ──────────────────────────────────────────────────────────────────────
def contract_identifiers(contract_source: str) -> list[tuple[int, str, str]]:
    """계약 파일의 **시그니처 식별자**(클래스·메서드·인자·필드·별칭) 전수 — (행, 역할, 이름).

    docstring 산문은 대상이 아니다(EOS-92 §2-1의 '치환맵' 은유는 이 축이 못 본다 — 정직한 공백).
    어휘 판정은 여기서 하지 않는다: 수학 어휘 목록은 `eos_core_boundary_probe.py`가 단일 원천이고
    호출측(테스트)이 그 술어를 넘긴다.
    """
    out: list[tuple[int, str, str]] = []
    tree = ast.parse(contract_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.append((node.lineno, "class", node.name))
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    out.append((stmt.lineno, "field", stmt.target.id))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.lineno, "method", node.name))
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
                out.append((arg.lineno, "arg", arg.arg))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id[:1].isupper():
                out.append((node.lineno, "alias", t.id))  # VerificationState = Literal[...]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
