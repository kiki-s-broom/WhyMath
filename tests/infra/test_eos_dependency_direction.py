"""EOS Core 허용 의존 방향 — 계획서 100 §3.8 (EOS-88).

§3.8은 두 그림을 준다. 권장 방향은 ``Application → EOS Core → Subject Contract → Math Adapter``
이고, 실행 시 어댑터가 Core에 *등록*되는 형태라면 실제 의존 역전은
``EOS Core → Subject Interface ← Math Adapter`` 가 더 정확하다 — **Core는 Math Adapter 구현체를
몰라야 한다**. 이 파일은 그 문장을 네 화살표로 나눠 AST로 잰다:

1. **Interface → Adapter 금지** — `schema.subject_adapter`·`schema.verification_capabilities`는
   `schema` 밖을 import하지 않는다(함수 안 지연 import도 본다).
2. **Adapter → Interface 필수** — `l4.subject_adapter_math`는 인터페이스를 import하고 적합성 증명
   (`: SubjectAdapter = MathSubjectAdapter()`)을 갖는다. 화살표가 *위로* 향한다는 증거다.
3. **Core는 구현체를 모른다** — CORE 코드(docstring 제외)에 어댑터 클래스 이름·모듈명이 0.
4. **Core → Application 금지** — `l*`·`schema`·`lang`·`composition`이 `api`·`app`·`main`을 모른다.

그리고 §3.8이 "덜 정확하다"고 한 형태 — Core가 합성 루트에서 기본 구현을 **끌어오는(pull)**
자리 — 를 집합으로 동결한다. 늘면 RED, 줄면 ratchet. 등록(push) 형태로 바꾸는 일은 별도
태스크(EOS-89)이며, 이 파일은 그 전환이 *진행되는지*를 그 집합의 크기로 본다.

정본화 ≠ 집행: 1·3의 *직접 import*는 EOS-67 import-linter 계약이 이미 강제한다(schema가 source).
이 파일이 더 보는 것은 지연 import·이름·문자열·pull 지점이다.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG = _REPO_ROOT / "src" / "backend" / "whymath_backend"
_PYPROJECT = _REPO_ROOT / "src" / "backend" / "pyproject.toml"
_PROBE = _REPO_ROOT / "scripts" / "analysis" / "eos_core_boundary_probe.py"
_BOUNDARY_DOC = _REPO_ROOT / "docs" / "architecture" / "eos_core_adapter_boundary.md"

INTERFACE_MODULES = ("schema.subject_adapter", "schema.verification_capabilities")
ADAPTER_MODULE = "l4.subject_adapter_math"
COMPOSITION_MODULE = "composition"
APPLICATION_PREFIXES = ("whymath_backend.api", "whymath_backend.app", "whymath_backend.main")

# 어댑터 구현체의 이름 — Core 코드에 하나라도 나타나면 "Core가 구현체를 안다".
ADAPTER_IMPL_NAMES: frozenset[str] = frozenset(
    {
        "MathSubjectAdapter",
        "MathExpressionEquivalence",
        "MathFinalAnswerVerifier",
        "MathAssessmentAnswerVerifier",
        "MathExpressionSeal",
        "MathAnswerFormVerifier",
        "MathStepChainVerifier",
    }
)
ADAPTER_IMPL_MODULE_TOKEN = "subject_adapter_math"

# 합성 루트에서 기본 구현을 *끌어오는* **CORE** 모듈 — §3.8의 "덜 정확한" 형태. 줄이는 방향으로만.
# EOS-89가 기존 3건을 0으로 줄였다: `api.coach`는 app.state Depends로, `l3.render.adapters`는
# 어댑터 생성자 주입으로, `l3.pedagogy.slot_generator`는 호출부 파라미터로 각각 바뀌었다.
# [EOS-86, EOS-89와 병행 개발] `l4.solution_coaching`이 신규 1건으로 남는다 — verify_solution
# 직접 import를 걷어내는 대가로 이 모듈이 합성 루트에서 StepChainVerifier 기본 구현을 지연
# 조회한다.
# [COMP-01] 그 능력의 *서빙* 경로는 push로 바뀌었다(app.py 등록 + api.coach 3핸들러 명시 주입).
# 그럼에도 이 baseline이 줄지 않는 이유는 두 가지이며, 둘 다 소스에서 확인된다:
#   ① 단위테스트 편의 폴백(`if verifier is None: from ...composition import ...`)이 남아 있다 —
#      지우면 `recommend_coaching_for_solution`을 직접 부르는 300+ 테스트가 전부 verifier를
#      만들어 넘겨야 한다.
#   ② 설령 ①을 지워도 같은 모듈이 `default_wrong_form_shadow_observer`를 지연 조회하므로 간선은
#      남는다. 즉 이 baseline의 축소 조건은 "두 폴백을 모두 걷어내는 것"이다.
# 이 항목을 지우려는 사람은 위 두 import를 먼저 없애야 한다(그러지 않으면 이 테스트가 RED).
CORE_PULL_BASELINE: frozenset[str] = frozenset({"l4.solution_coaching"})

# 합성 루트를 소비해도 되는 **비-CORE** 모듈 — 프로세스가 시작되는 자리(=합성 루트의 정의).
# 여기 있는 것은 "허용"이 아니라 **회계**다: 이 집합이 정확히 이 값이어야 통과하므로, 어느
# 모듈이든 조용히 합성 루트를 쓰기 시작하면 RED가 된다(늘어도·줄어도).
#   · `app`      — ASGI 앱 팩토리. 부팅 시 능력 5종을 app.state에 등록한다(EOS-89 ①).
#   · `harness.concept_assessment_index` — 렌더 성공률 측정 CLI(`main()` 보유). 어댑터를 직접
#     조립하므로 능력이 필요하고, 그 능력을 줄 상류가 없다(프로세스의 시작이 자기 자신이다).
NON_CORE_COMPOSITION_CONSUMERS: frozenset[str] = frozenset(
    {"app", "harness.concept_assessment_index"}
)

# app.py가 `app.state`에 올려야 하는 과목 능력 키 상수명 — `api/_subject_capability_state.py`가
# 정본이고, 이 목록은 그 정본과 대조된다(이름을 두 곳에 손으로 적어 두지 않는다).
SUBJECT_CAPABILITY_STATE_MODULE = "api._subject_capability_state"

# 합성 루트 팩토리 중 app.py가 부르지 **않아도 되는** 것들. 이 집합이 하는 일은 하나다 —
# `test_app_factory_calls_every_composition_factory`가 "app.py가 반드시 호출해야 하는 팩토리"를
# 계산할 때 전체 팩토리에서 이만큼을 뺀다. 즉 **여기 남은 것은 app.py가 부르지 않는 것이 정상**이고,
# 여기서 빠지는 순간 app.py 호출이 강제된다.
# [COMP-01] `default_step_chain_verifier`는 app.state 등록(push) 대상이 되어 이 집합에서 빠졌다 —
# app.py가 이제 실제로 호출한다. 남은 `default_wrong_form_shadow_observer`는 애초에 "능력"이 아닌
# 관측기(`Callable[[str], None]`·fire-and-forget)라 등록 대상이 아니며, `l4.solution_coaching`이
# 지연 조회한다.
# CORE_PULL_BASELINE과의 관계(더 이상 1:1 이중 회계가 아니다): step chain은 **양쪽 형태가 공존**
# 한다 — 서빙 3경로는 push 주입이고(그래서 여기서 빠짐), 단위테스트용 폴백 지연 import는 소스에
# 남는다(그래서 `l4.solution_coaching`은 CORE_PULL_BASELINE에 잔존). 그 잔존은 관측기 폴백만으로도
# 성립하므로, 이 집합에서 능력이 빠졌다고 저 집합이 줄어야 하는 것이 아니다.
PULL_ONLY_COMPOSITION_FACTORIES: frozenset[str] = frozenset({"default_wrong_form_shadow_observer"})


# ──────────────────────────────────────────────────────────────────────
# 스캐너 (순수 함수 — 결함 주입 테스트가 직접 부른다)
# ──────────────────────────────────────────────────────────────────────


def absolute_imports(source: str) -> set[str]:
    """모듈·클래스·함수 본문 어디에 있든 절대 import 대상 모듈 이름 전부(지연 import 포함)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module)
    return out


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


def code_mentions(source: str, names: frozenset[str], module_token: str) -> list[str]:
    """docstring을 제외한 코드에서 이름(Name/Attribute)·문자열 상수·import가 구현체를 가리키는 곳."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            hits.append(f"L{node.lineno} name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in names:
            hits.append(f"L{node.lineno} attr {node.attr}")
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
        ):
            if module_token in node.value or any(n in node.value for n in names):
                hits.append(f"L{node.lineno} str {node.value[:60]!r}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""] + [a.name for a in node.names]
            )
            if any(module_token in m or m in names for m in mods):
                hits.append(f"L{node.lineno} import {mods}")
    return hits


def conformance_proofs(source: str) -> list[tuple[str, str]]:
    """`_X: SubjectAdapter = MathSubjectAdapter()` 꼴 — (프로토콜, 구현체) 쌍."""
    out: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.annotation, ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            out.append((node.annotation.id, node.value.func.id))
    return out


# ──────────────────────────────────────────────────────────────────────
# 모집단
# ──────────────────────────────────────────────────────────────────────


def _module_path(mod: str) -> Path:
    p = _PKG / (mod.replace(".", "/") + ".py")
    return p if p.exists() else _PKG / mod.replace(".", "/") / "__init__.py"


def _all_modules() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in _PKG.rglob("*.py"):
        rel = p.relative_to(_PKG).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            out[".".join(parts)] = p
    return out


def _load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("_eos_core_boundary_probe_for_direction", _PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def core_modules() -> list[str]:
    probe = _load_probe()
    inv = probe._load_inventory()
    scan = inv._load_script(inv.SCAN_SCRIPT, "_eos_boundary_scan_for_direction")
    core = [m for m in inv._backend_modules() if scan.classify(m)[0] == "CORE"]
    if len(core) < 200:  # 스캔 0건은 실패 — 공허한 통과 금지(CLAUDE.md 2026-09-01 ④)
        raise RuntimeError(f"CORE 모집단이 비정상적으로 작다: {len(core)}")
    return core


# ──────────────────────────────────────────────────────────────────────
# ① 네 화살표
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mod", INTERFACE_MODULES)
def test_subject_interface_imports_nothing_below_schema(mod: str) -> None:
    """Interface → Adapter(또는 어느 계층이든) 금지 — 인터페이스는 schema 안에서만 닫힌다."""
    imports = absolute_imports(_module_path(mod).read_text(encoding="utf-8"))
    ours = {m for m in imports if m.startswith("whymath_backend")}
    leaks = {m for m in ours if not m.startswith("whymath_backend.schema")}
    assert not leaks, f"{mod}가 schema 밖을 import: {sorted(leaks)}"


def test_math_adapter_points_up_at_the_interface() -> None:
    """Adapter → Interface: 두 인터페이스 모듈을 import하고 필수층 적합성 증명을 갖는다."""
    src = _module_path(ADAPTER_MODULE).read_text(encoding="utf-8")
    imports = absolute_imports(src)
    for iface in INTERFACE_MODULES:
        assert f"whymath_backend.{iface}" in imports, f"어댑터가 {iface}를 import하지 않는다"
    proofs = conformance_proofs(src)
    assert ("SubjectAdapter", "MathSubjectAdapter") in proofs, proofs


def test_core_code_never_names_an_adapter_implementation(core_modules: list[str]) -> None:
    """Core는 Math Adapter 구현체를 몰라야 한다 — 이름·속성·문자열·import 어디에도(docstring 제외)."""
    offenders: dict[str, list[str]] = {}
    for mod in core_modules:
        if mod == COMPOSITION_MODULE:
            continue  # 합성 루트는 정의상 구현체를 아는 유일한 자리(INFRA)
        path = _module_path(mod)
        if not path.exists():
            continue
        hits = code_mentions(
            path.read_text(encoding="utf-8"), ADAPTER_IMPL_NAMES, ADAPTER_IMPL_MODULE_TOKEN
        )
        if hits:
            offenders[mod] = hits
    assert offenders == {}, f"CORE 코드가 어댑터 구현체를 안다: {offenders}"


def test_core_never_imports_the_application(core_modules: list[str]) -> None:
    """Core → Application 금지 — CORE 배정 모듈이 api/app/main을 모른다.

    INFRA 배정의 운영 CLI(`ops.*`·`harness.*`·`privacy.*`)는 이 검사 대상이 아니다 — 그들은
    Application 쪽에 서서 api 헬퍼를 쓰는 도구다(실측 8모듈 · 경계 문서 §9.2에 기록).
    """
    offenders: dict[str, set[str]] = {}
    for mod in core_modules:
        if mod.split(".")[0] in {"api", "app", "main"}:
            continue
        path = _module_path(mod)
        if not path.exists():
            continue
        imports = absolute_imports(path.read_text(encoding="utf-8"))
        bad = {m for m in imports if m.startswith(APPLICATION_PREFIXES)}
        if bad:
            offenders[mod] = bad
    assert offenders == {}, offenders


# ──────────────────────────────────────────────────────────────────────
# ② 등록(push) vs 풀(pull)
# ──────────────────────────────────────────────────────────────────────


def _composition_importers() -> set[str]:
    """`whymath_backend.composition`을 import하는 모듈 전부(합성 루트 자신·어댑터 제외)."""
    out: set[str] = set()
    for mod, path in _all_modules().items():
        if mod in {COMPOSITION_MODULE, ADAPTER_MODULE}:
            continue
        imports = absolute_imports(path.read_text(encoding="utf-8"))
        if f"whymath_backend.{COMPOSITION_MODULE}" in imports:
            out.add(mod)
    return out


def _pull_points(core: list[str]) -> set[str]:
    """그중 **CORE 배정** 모듈 — §3.8이 "덜 정확하다"고 한 형태(Core가 배선을 안다)."""
    return _composition_importers() & set(core)


def test_core_pull_points_from_composition_are_frozen_and_only_shrink(
    core_modules: list[str],
) -> None:
    observed = _pull_points(core_modules)
    new = observed - CORE_PULL_BASELINE
    assert (
        not new
    ), f"새 pull 지점(Core가 합성 루트에서 구현을 끌어옴 — §3.8 위반 방향): {sorted(new)}"
    if observed < CORE_PULL_BASELINE:
        pytest.fail(f"pull 지점이 줄었다 — CORE_PULL_BASELINE을 {sorted(observed)}로 ratchet")


def test_non_core_composition_consumers_are_accounted_for(core_modules: list[str]) -> None:
    """비-CORE 소비자는 **정확히** 열거된 집합이어야 한다 — 늘어도 줄어도 RED.

    CORE 집합만 잠그면 `ops.*`·`harness.*`·`app`이 합성 루트를 조용히 쓰기 시작해도 아무 신호가
    없다. 그러면 "pull 0"은 사실이지만 무의미해진다(같은 결합이 라벨만 바꿔 옮겨 간 것). 그래서
    비-CORE 소비자도 회계 대상으로 둔다 — 늘리려면 이 목록을 **고쳐야** 하고, 그 편집이 곧
    "이 모듈은 엔트리포인트다"라는 선언이 된다.
    """
    observed = _composition_importers() - set(core_modules)
    assert observed == NON_CORE_COMPOSITION_CONSUMERS, (
        "합성 루트를 쓰는 비-CORE 모듈 집합이 바뀌었다 — 엔트리포인트라면 "
        f"NON_CORE_COMPOSITION_CONSUMERS를 {sorted(observed)}로 갱신하라: "
        f"추가={sorted(observed - NON_CORE_COMPOSITION_CONSUMERS)} "
        f"제거={sorted(NON_CORE_COMPOSITION_CONSUMERS - observed)}"
    )


def test_listed_non_core_consumers_really_are_entry_points() -> None:
    """열거된 비-CORE 소비자가 실제로 **엔트리포인트**인가 — `app` 또는 `main()` 보유 모듈.

    목록에 이름을 적는 것만으로 면제되면 이 회계는 서명란이 된다. 그래서 "엔트리포인트"라는
    주장 자체를 소스로 검증한다(합성 루트 = 프로세스가 시작되는 자리라는 정의의 기계 판).
    """
    for mod in sorted(NON_CORE_COMPOSITION_CONSUMERS):
        if mod == "app":
            continue  # ASGI 앱 팩토리 — 프로세스 진입 그 자체.
        src = _module_path(mod).read_text(encoding="utf-8")
        tree = ast.parse(src)
        has_main = any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main"
            for n in tree.body
        )
        assert has_main, f"{mod}는 엔트리포인트가 아니다(main() 없음) — 합성 루트 소비 정당화 실패"


def test_layer_pull_edges_and_the_layers_contract_agree_exactly() -> None:
    """합성 루트가 세탁 통로가 되지 않게 — l* 풀 간선과 pyproject 면제 줄이 **정확히** 일치한다.

    양방향으로 잰다. 적히지 않은 간선이 있으면 면제 없이 계층을 건너뛰는 것이고, 간선이 없는데
    면제 줄이 남아 있으면 **죽은 면제**다(import-linter의 `unmatched_ignore_imports_alerting`이
    같은 것을 보지만, 그 설정이 꺼지는 날 이 검사가 남는다). EOS-89 이후 양쪽 모두 공집합이며,
    그 사실이 "l* Core가 합성 루트를 모른다"의 계약측 증거다.
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    layers = next(c for c in data["tool"]["importlinter"]["contracts"] if c.get("type") == "layers")
    ignores = {
        line
        for line in layers.get("ignore_imports", [])
        if line.endswith(f"-> whymath_backend.{COMPOSITION_MODULE}")
    }
    # api는 layers 최상단 — 합성 루트 import가 역방향이 아니라 면제가 필요 없다.
    edges = {
        f"whymath_backend.{mod} -> whymath_backend.{COMPOSITION_MODULE}"
        for mod in _composition_importers()
        if mod.startswith("l")
    }
    assert edges == ignores, (
        "합성 루트 면제 줄과 실제 간선이 어긋난다 — "
        f"면제 누락={sorted(edges - ignores)} 죽은 면제={sorted(ignores - edges)}"
    )


def _app_state_registered_keys() -> set[str]:
    """`app.py`의 `app.state.__setattr__(KEY, expr)` 호출에서 KEY **상수명**을 모은다.

    인벤토리 v2의 DI 다리(`scripts/analysis/eos_feature_inventory_v2.py::_app_state_di_map`)와
    **같은 형태**를 읽는다 — 그 도구가 못 보는 방식으로 등록하면 등록은 되지만 정적 분석에서
    사라지므로, 여기서 같은 파서 형태를 요구해 두 도구의 시야를 일치시킨다.
    """
    tree = ast.parse((_PKG / "app.py").read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "__setattr__" or ast.unparse(node.func.value) != "app.state":
            continue
        if len(node.args) == 2 and isinstance(node.args[0], ast.Name):
            keys.add(node.args[0].id)
    return keys


def _capability_key_constants() -> set[str]:
    """`api/_subject_capability_state.py`가 정의한 능력 키 상수명(= 등록되어야 할 목록)."""
    tree = ast.parse(_module_path(SUBJECT_CAPABILITY_STATE_MODULE).read_text(encoding="utf-8"))
    return {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name) and t.id.endswith("_KEY")
    }


def test_app_factory_registers_every_subject_capability() -> None:
    """등록(push) 형태의 실재 — `app.py`가 능력 키 **전부**를 app.state에 올린다(EOS-89 ①).

    이 테스트는 EOS-88이 걸어 둔 잠금(`..._registers_no_subject_capability_yet`)을 **대체**한다.
    두 형태(pull·push)가 소리 없이 공존하지 않게 하려면 잠금을 남겨 두는 것이 아니라 방향을
    뒤집은 단언으로 바꿔야 한다 — 옛 잠금을 남기면 그 자체가 모순 게이트가 된다.

    별칭 import(`as _X`)를 쓰므로 상수명을 그대로 비교하지 않고 **접미사**로 잇는다
    (`EXPRESSION_SEAL_KEY` ↔ `_EXPRESSION_SEAL_KEY`).
    """
    registered = _app_state_registered_keys()
    required = _capability_key_constants()
    assert required, "능력 키 상수를 하나도 찾지 못했다 — 스캔 0건은 통과가 아니다"
    missing = {name for name in required if not any(r.lstrip("_") == name for r in registered)}
    assert not missing, f"app.state에 등록되지 않은 과목 능력 키: {sorted(missing)}"


def test_app_factory_calls_every_composition_factory() -> None:
    """등록값이 **합성 루트에서 온다** — app.py가 `composition`의 push 대상 팩토리를 전부 호출한다.

    키만 올리고 값이 딴 데서 오면 "등록 형태"라는 주장이 절반만 참이다. app.py가 import한
    `default_*` 이름과 합성 루트의 `__all__`을 대조해 누락을 잡는다. `PULL_ONLY_COMPOSITION_
    FACTORIES`에 실린 것은 app.py가 부르지 않는 것이 정상이므로 제외하되, **그 면제가 참인지도
    함께 잰다**(COMP-01) — 목록에 적힌 팩토리를 app.py가 실제로 부르고 있으면 그것은 면제가
    아니라 미갱신이므로 RED다. 한쪽 방향만 재면 면제 목록에 이름을 더하는 것만으로 이 게이트를
    조용히 끌 수 있다.
    """
    app_src = (_PKG / "app.py").read_text(encoding="utf-8")
    assert f"whymath_backend.{COMPOSITION_MODULE}" in absolute_imports(app_src)
    factories = {
        n.name
        for n in ast.walk(ast.parse(_module_path(COMPOSITION_MODULE).read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name.startswith("default_")
    }
    assert factories, "합성 루트에서 팩토리를 하나도 찾지 못했다 — 스캔 0건은 통과가 아니다"
    push_factories = factories - PULL_ONLY_COMPOSITION_FACTORIES
    called = {
        n.func.id
        for n in ast.walk(ast.parse(app_src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert (
        push_factories <= called
    ), f"app.py가 부르지 않는 합성 루트 팩토리: {sorted(push_factories - called)}"
    # [COMP-01] **역방향도 잰다** — 면제 목록이 한쪽으로만 잠겨 있으면 그 목록은 서명란이 된다.
    # 위 단언만 있을 때 `PULL_ONLY_COMPOSITION_FACTORIES`에 이름을 *더하면* push_factories가
    # 줄어들 뿐이라 항상 통과한다(실패 주입 실측 2026-09-07: step chain을 목록에 되돌려 넣어도
    # 22 passed — 면제 추가가 무증상이었다). 그래서 "여기 남은 것은 app.py가 부르지 않는 것이
    # 정상"이라는 이 목록의 정의 자체를 단언한다: 등록해 놓고 면제 목록에도 적어 두는 모순
    # 상태(둘 중 어느 쪽이 진실인지 읽는 사람이 알 수 없다)를 RED로 만든다.
    contradictory = PULL_ONLY_COMPOSITION_FACTORIES & called
    assert not contradictory, (
        "app.py가 부르는데 PULL_ONLY_COMPOSITION_FACTORIES에도 실려 있다 — 등록(push)됐다면 "
        f"목록에서 빼라: {sorted(contradictory)}"
    )


# ──────────────────────────────────────────────────────────────────────
# ③ 변별력 — 결함 주입
# ──────────────────────────────────────────────────────────────────────


def test_scanner_catches_lazy_import_inside_a_function() -> None:
    src = "def f():\n    from whymath_backend.l4.subject_adapter_math import MathSubjectAdapter\n"
    assert "whymath_backend.l4.subject_adapter_math" in absolute_imports(src)
    assert code_mentions(src, ADAPTER_IMPL_NAMES, ADAPTER_IMPL_MODULE_TOKEN)


@pytest.mark.parametrize(
    "src",
    [
        "x = MathSubjectAdapter()\n",
        "y = mod.MathExpressionSeal\n",
        'p = "whymath_backend.l4.subject_adapter_math"\n',
        "import whymath_backend.l4.subject_adapter_math as m\n",
    ],
)
def test_scanner_detects_injected_implementation_knowledge(src: str) -> None:
    assert len(code_mentions(src, ADAPTER_IMPL_NAMES, ADAPTER_IMPL_MODULE_TOKEN)) == 1


@pytest.mark.parametrize(
    "src",
    [
        '"""MathSubjectAdapter가 구현한다 — docstring."""\nx = 1\n',
        'def f():\n    """subject_adapter_math를 본다."""\n    return 1\n',
        "from whymath_backend.schema.subject_adapter import SubjectAdapter\n",
        'kind = "quadratic"\n',
    ],
)
def test_scanner_ignores_docstrings_and_interface_imports(src: str) -> None:
    assert code_mentions(src, ADAPTER_IMPL_NAMES, ADAPTER_IMPL_MODULE_TOKEN) == []


def test_conformance_scanner_reads_the_proof_shape() -> None:
    src = "_P: SubjectAdapter = MathSubjectAdapter()\n_Q = MathSubjectAdapter()\n"
    assert conformance_proofs(src) == [("SubjectAdapter", "MathSubjectAdapter")]


# ──────────────────────────────────────────────────────────────────────
# ④ 정본 문서 배선
# ──────────────────────────────────────────────────────────────────────


def test_boundary_doc_records_the_direction_measurement() -> None:
    doc = _BOUNDARY_DOC.read_text(encoding="utf-8")
    assert "§9" in doc and "허용 의존 방향" in doc and "test_eos_dependency_direction.py" in doc
