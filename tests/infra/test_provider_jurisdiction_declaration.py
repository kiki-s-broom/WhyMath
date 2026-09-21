"""프로바이더 관할 선언의 **전수 거버넌스** — AST 기반 (ARCH-49 ⑤).

왜 이 테스트가 필요한가
----------------------
`CompositeProvider.cloud_jurisdiction`은 관할을 선언하지 않은 제공자에게 기본값
`Jurisdiction.US`를 준다. 그 기본값은 *넓은* 쪽이라 그것만으로는 fail-closed가 아니다 —
새 클라우드 프로바이더를 붙이면서 선언을 잊으면 **그 순간 조용히 미국 법인으로 취급**되고,
관할 축 전체가 무의미해진다. 기본값을 좁은 쪽(UNKNOWN)으로 뒤집으면 이번엔 관할과 무관한
테스트 가짜 수십 개가 전부 막힌다.

그래서 기본값은 넓게 두되 **프로덕션 제공자에게는 선언을 기계로 요구**한다. 이 테스트가 그
요구다: `l3/providers/`의 실제 제공자 클래스는 전부 `jurisdiction`을 선언해야 한다.

문자열이 아니라 **구성된 결과**를 본다(CLAUDE.md「금지 패턴 열거 대신 산출물 검사」):
소스에 `jurisdiction`이라는 글자가 있는지가 아니라, AST에서 *그 클래스의 멤버로*
`jurisdiction`이 정의됐고 그 값이 `Jurisdiction` enum 멤버인지를 판정한다. 주석·docstring·
다른 클래스의 선언으로는 통과하지 못한다.

**스캔 0건은 실패다** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.

배선 메모 (CLAUDE.md 「검증 장치를 만들고 배선 확인 없이 완료 선언 금지」): 이 파일이 도는
CI 잡은 `infra-contracts`이고, **그 잡은 백엔드 패키지를 설치하지 않는다**(실측 2026-09-17 —
`pip install pytest pytest-asyncio pytest-randomly pyyaml sqlalchemy ruff black` 7종뿐).
그래서 `whymath_backend`를 import하지 않고 소스를 AST로 읽는다 — import하면 저장소에서는
통과하고 CI에서만 ImportError로 죽는다. `tests/infra`의 다른 계약 테스트들이 전부 같은
규율을 지킨다(백엔드 심볼은 *문자열 픽스처*로만 등장한다).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_L3_DIR = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "l3"
_PROVIDERS_DIR = _L3_DIR / "providers"
_JURISDICTION_MODULE = _L3_DIR / "provider_jurisdiction.py"

# 디스패처는 제공자가 아니다 — 남의 관할을 *읽는* 쪽이라 자기 관할이 없다.
_DISPATCHERS = frozenset({"CompositeProvider"})

_JURISDICTION_MEMBER = "jurisdiction"


def _jurisdiction_member_names() -> frozenset[str]:
    """`Jurisdiction` enum의 멤버 이름 — 소스를 AST로 읽는다(import하지 않는 이유는 위 메모).

    수집 0건은 실패다: enum을 못 읽었는데 빈 집합을 돌려주면 아래 오타 검사가 *모든* 값을
    위반으로 잡거나(과잉) 검사 자체가 무의미해진다.
    """
    tree = ast.parse(_JURISDICTION_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Jurisdiction":
            names = {
                target.id
                for item in node.body
                if isinstance(item, ast.Assign)
                for target in item.targets
                if isinstance(target, ast.Name)
            }
            assert names, "Jurisdiction enum에서 멤버를 하나도 읽지 못했다"
            return frozenset(names)
    raise AssertionError(
        f"{_JURISDICTION_MODULE.relative_to(_REPO_ROOT)}에서 Jurisdiction 선언을 찾지 못했다"
    )


def _provider_classes() -> list[tuple[Path, ast.ClassDef]]:
    """`async def generate`를 정의하는 클래스 = 실제 제공자 (Protocol 선언은 제외).

    `_Messages`·`_AnthropicClient` 같은 *클라이언트 시임* Protocol도 `async def`를 갖지만
    이름이 `generate`가 아니거나(create/list) Protocol 상속이라 걸러진다. 판정을 이름 규칙
    (`*Provider`)에 맡기지 않는 이유는 그 규칙이 곧 우회 경로이기 때문이다 — 이름을
    `DeepSeekBackend`로 지으면 스캔에서 빠진다.
    """
    found: list[tuple[Path, ast.ClassDef]] = []
    for path in sorted(_PROVIDERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if _is_protocol(node):
                continue
            has_generate = any(
                isinstance(item, ast.AsyncFunctionDef) and item.name == "generate"
                for item in node.body
            )
            if has_generate:
                found.append((path, node))
    return found


def _is_protocol(node: ast.ClassDef) -> bool:
    """`Protocol`을 직접 상속하는 선언(구현이 아니라 *경계*)인가."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _declared_jurisdiction_values(node: ast.ClassDef) -> list[str]:
    """클래스 멤버 `jurisdiction`이 돌려주는 `Jurisdiction.<NAME>` 목록 (없으면 빈 목록).

    `@property def jurisdiction` 형태와 클래스 속성 `jurisdiction = Jurisdiction.X`
    형태를 모두 본다. 반환 표현식이 `Jurisdiction.<NAME>`이 아니면(계산된 값 등) 이름을
    수집하지 못하지만, 그 경우에도 *멤버는 존재*하므로 선언 자체는 인정한다 — 유도형
    관할(`OpenRouterProvider.jurisdiction`)이 정당한 형태이기 때문이다.
    """
    values: list[str] = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == _JURISDICTION_MEMBER:
            for sub in ast.walk(item):
                if (
                    isinstance(sub, ast.Attribute)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "Jurisdiction"
                ):
                    values.append(sub.attr)
        elif isinstance(item, ast.AnnAssign | ast.Assign):
            targets = [item.target] if isinstance(item, ast.AnnAssign) else item.targets
            named = any(isinstance(t, ast.Name) and t.id == _JURISDICTION_MEMBER for t in targets)
            if named and item.value is not None:
                for sub in ast.walk(item.value):
                    if (
                        isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "Jurisdiction"
                    ):
                        values.append(sub.attr)
    return values


def _local_base_names(node: ast.ClassDef) -> list[str]:
    """이 클래스가 상속한 *단순 이름* 기반클래스 목록(`Protocol`·점 표기 제외)."""
    return [base.id for base in node.bases if isinstance(base, ast.Name)]


def _declares_jurisdiction(node: ast.ClassDef, by_name: dict[str, ast.ClassDef]) -> bool:
    """이 클래스의 **인스턴스가** 관할을 갖는가 — 본문 선언 또는 **상속**으로 충족된다.

    상속을 인정하는 이유는 실재하는 형태이기 때문이다: `FixedModelOllamaProvider`는
    `OllamaProvider`를 상속해 `_get_client`·추출기를 재사용하는 측정 전용 좌석이고,
    관할은 기반 클래스의 것을 그대로 물려받는 것이 **옳다**(같은 Ollama 데몬을 부른다).
    본문 선언만 요구하면 그런 좌석이 의미 없는 중복 선언을 강요받고, 그 강요가 쌓이면
    사람이 게이트를 끈다.

    기반 클래스 해석은 `l3/providers/` 안의 이름으로만 한다 — 패키지 밖 상속은 이 스캐너가
    추적할 수 없으므로 *선언 없음*으로 본다(fail-closed). 순환 상속은 방문 집합으로 끊는다.
    """
    seen: set[str] = set()
    stack = [node]
    while stack:
        current = stack.pop()
        if current.name in seen:
            continue
        seen.add(current.name)
        if _has_jurisdiction_member(current):
            return True
        stack.extend(by_name[name] for name in _local_base_names(current) if name in by_name)
    return False


def _has_jurisdiction_member(node: ast.ClassDef) -> bool:
    """클래스 본문에 `jurisdiction` 멤버가 정의됐는가(이름 일치 — 값은 따로 본다)."""
    for item in node.body:
        if (
            isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            and item.name == _JURISDICTION_MEMBER
        ):
            return True
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            if item.target.id == _JURISDICTION_MEMBER:
                return True
        if isinstance(item, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == _JURISDICTION_MEMBER for t in item.targets):
                return True
    return False


def test_scan_finds_the_known_providers() -> None:
    """스캔 0건·대상 누락은 실패다 — 공허하게 통과하는 전수 가드를 만들지 않는다."""
    names = {node.name for _, node in _provider_classes()}
    assert names, "제공자 클래스를 하나도 찾지 못했다 — 스캔 자체가 고장났다"
    # 알려진 4종이 전부 잡히는지 확인(분류 규칙이 조용히 좁아지면 여기서 드러난다).
    assert {
        "OllamaProvider",
        "AnthropicProvider",
        "DeepSeekProvider",
        "OpenRouterProvider",
        # 측정 전용 서브클래스 — 상속 절이 없으면 여기서 red가 난다(그 절의 반례).
        "FixedModelOllamaProvider",
    } <= names
    # 디스패처도 `generate`를 가지므로 스캔에는 잡힌다 — 제외 목록이 그것을 다룬다.
    assert "CompositeProvider" in names


@pytest.mark.parametrize(
    ("relative_path", "class_name"),
    [
        (str(path.relative_to(_REPO_ROOT)), node.name)
        for path, node in _provider_classes()
        if node.name not in _DISPATCHERS
    ],
)
def test_every_provider_declares_its_jurisdiction(relative_path: str, class_name: str) -> None:
    """실제 제공자는 전부 관할을 선언한다 — 기본값(US)에 기대는 좌석을 남기지 않는다."""
    classes = _provider_classes()
    by_name = {node.name: node for _, node in classes}
    node = next(
        node
        for path, node in classes
        if node.name == class_name and str(path.relative_to(_REPO_ROOT)) == relative_path
    )
    assert _declares_jurisdiction(node, by_name), (
        f"{relative_path}의 {class_name}이 jurisdiction을 선언하지 않았다(상속으로도 없다) — "
        "선언이 없으면 CompositeProvider가 기본값(US)으로 취급해 관할 축이 무력해진다. "
        "`@property def jurisdiction(self) -> Jurisdiction:`을 추가하라."
    )


def test_jurisdiction_enum_members_are_readable() -> None:
    """enum 수집기의 자가검증 — 알려진 관할 4종이 잡히는가(수집 실패를 통과로 읽지 않는다)."""
    assert _jurisdiction_member_names() == {"DOMESTIC", "US", "CN", "UNKNOWN"}


def test_declared_values_are_real_jurisdiction_members() -> None:
    """선언에 등장한 `Jurisdiction.<NAME>`이 전부 실제 enum 멤버인가(오타 방지)."""
    valid = _jurisdiction_member_names()
    seen: set[str] = set()
    for path, node in _provider_classes():
        for value in _declared_jurisdiction_values(node):
            assert value in valid, (
                f"{path.relative_to(_REPO_ROOT)}의 {node.name}이 존재하지 않는 관할 "
                f"`Jurisdiction.{value}`를 선언했다"
            )
            seen.add(value)
    assert seen, "관할 선언 값을 하나도 수집하지 못했다 — 수집기가 고장났다"


def test_detector_rejects_a_provider_without_declaration() -> None:
    """탐지기 자신의 변별력 — 선언 없는 제공자를 주입하면 실제로 False를 낸다.

    이 단언이 없으면 `_has_jurisdiction_member`가 항상 True를 돌려줘도 위 전수 테스트가
    통과한다(모든 입력에서 초록인 가드). 주입이 실제로 적용됐는지도 함께 단언한다.
    """
    source = (
        "class Sneaky:\n"
        "    async def generate(self, prompt, system, decision):\n"
        "        return None\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    assert any(
        isinstance(item, ast.AsyncFunctionDef) and item.name == "generate" for item in node.body
    ), "픽스처가 제공자 형태가 아니다 — 주입이 탐지기에 닿지 않는다"
    assert _has_jurisdiction_member(node) is False


@pytest.mark.parametrize(
    "declaration",
    [
        # 프로퍼티 형태(현행 4종이 쓰는 형태)
        "    @property\n    def jurisdiction(self):\n        return Jurisdiction.CN\n",
        # 클래스 속성 형태 — 미래의 다른 표기도 인정해야 한다(표기 변형에 뚫리지 않게)
        "    jurisdiction = Jurisdiction.US\n",
        "    jurisdiction: Jurisdiction = Jurisdiction.US\n",
    ],
)
def test_detector_accepts_each_declaration_form(declaration: str) -> None:
    """탐지기의 green 축 — 정당한 선언 형태를 위반으로 잡으면 개발 차단기가 된다."""
    source = (
        "class Fine:\n"
        f"{declaration}"
        "    async def generate(self, prompt, system, decision):\n"
        "        return None\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    assert _has_jurisdiction_member(node) is True


def test_inherited_declaration_counts() -> None:
    """상속 절을 밟는 픽스처 — 이 절이 없으면 `FixedModelOllamaProvider`가 위반으로 잡힌다.

    그것이 바로 이 절을 만들게 한 실제 사례다(2026-09-17: 초판 탐지기가 본문 선언만 보고
    그 측정 전용 좌석을 red로 잡았다).
    """
    source = (
        "class Base:\n"
        "    @property\n"
        "    def jurisdiction(self):\n"
        "        return Jurisdiction.DOMESTIC\n"
        "\n"
        "class Derived(Base):\n"
        "    async def generate(self, prompt, system, decision):\n"
        "        return None\n"
    )
    module = ast.parse(source)
    by_name = {node.name: node for node in module.body if isinstance(node, ast.ClassDef)}
    derived = by_name["Derived"]
    # 픽스처가 그 절을 실제로 밟는지 먼저 단언한다 — 본문 선언이 *없어야* 상속 절이 쓰인다.
    assert _has_jurisdiction_member(derived) is False
    assert _declares_jurisdiction(derived, by_name) is True


def test_declaration_outside_the_package_is_not_credited() -> None:
    """추적할 수 없는 기반 클래스는 *선언 없음*이다(fail-closed) — 이름만 보고 믿지 않는다."""
    source = (
        "class Orphan(SomethingElsewhere):\n"
        "    async def generate(self, prompt, system, decision):\n"
        "        return None\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    assert _local_base_names(node) == ["SomethingElsewhere"]
    assert _declares_jurisdiction(node, {node.name: node}) is False


def test_protocol_declarations_are_not_treated_as_providers() -> None:
    """클라이언트 시임 Protocol은 제공자가 아니다 — 그것까지 요구하면 개발 차단기가 된다."""
    source = (
        "class _Seam(Protocol):\n" "    async def generate(self, prompt, system, decision): ...\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    assert _is_protocol(node) is True
