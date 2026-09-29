"""ARCH-57 도입 · ARCH-64 전환 — 클라우드 슬롯 셀렉터의 계약 동결 (정본화 ≠ 집행).

네 가지를 기계로 강제한다. 넷이 서로 다른 실패 모드를 겨냥하므로 하나로 합치지 않는다:

  ① **기본값 = `openrouter`** (ARCH-64). ARCH-57 시절 이 자리는 "기본값 `anthropic` 불변"을
     동결했다 — ARCH-55 채택 판정문의 "기본 핀 불변" 조항이다. **그 조항은 번복됐다**: 2026-09-21
     Kiki 지시("학생 대면까지 한 번에" → "학생대면도 오픈라우터로 전환")와 같은 날 clear된 게이트
     `G-cloud-mid-seat-cutover`(판정 ① 저작+학생 대면 동시 컷오버)가 근거다. 판정문 원문은 지우지
     않고 번복 표기를 덧붙였다(`docs/ops/arch55_provider_battle_smoke_runbook.md`). 기본값을
     옮기는 것이 여전히 코드 변경이 아니라 판정이라는 점은 그대로다 — 그래서 산문이 아니라 여기서
     막는다.
  ② **집행 지점** — 저작 경로가 실제로 팩토리를 경유한다. `AnthropicProvider()`를 다시
     하드코딩하면 red. **AST 전수 스캔**이며 문자열 금지목록이 아니다 — 별칭 import·줄바꿈·
     주석 같은 표기 변형에서 뚫리지 않게 *구성된 결과*를 본다(CLAUDE.md 「금지 패턴 열거 대신
     산출물 검사」).
  ③ **학생 대면도 팩토리 경유** (ARCH-64 — ARCH-57의 "제외 동결"을 **반대 방향 가드**로 교체).
     `app.py`의 `CompositeProvider(cloud=...)` 좌석 조립 자리가 `build_cloud_provider()` 호출이어야
     하고, 클라우드 제공자 클래스를 직접 만들면 red다. 가드는 여전히 **좌석 조립 위치**를 본다.
  ④ **스캔 0건은 실패** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.

hermetic: 소스 AST와 `Settings` 기본값만 읽는다 — 네트워크·키·DB 0.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.providers.factory import build_cloud_provider, cloud_provider_name

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_SRC = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# 저작 경로 — 이 파일들은 클라우드 좌석을 팩토리에서 받아야 한다(main a036fa6b 실측 목록).
# `harness/problem_corpus_accumulate.py`는 여기 없다: 그 배치는 생성기에 `None`을 넘겨
# `l3/equivalent/llm_generator.py`의 지연 조립을 **상속**하므로 자기 자리에 좌석 이름이 없다.
# 즉 목록에 없는 것이 누락이 아니라, 하드코딩할 자리 자체가 없다는 뜻이다.
_AUTHORING_SITES: tuple[str, ...] = (
    "l3/equivalent/llm_generator.py",
    "l3/equivalent/rephrase.py",
    "l3/pregenerate/__main__.py",
    "l3/pedagogy/explanation_generator.py",
    "l3/pedagogy/analogy_generator.py",
    "l3/multi_solution.py",
    "l3/cross_verify.py",
)

# 학생 대면 서빙 — ARCH-64부터 **반드시** 팩토리를 경유한다(아래 ③ 참조).
_STUDENT_FACING = "app.py"

_FACTORY_FUNC = "build_cloud_provider"
_HARDCODED_CLASS = "AnthropicProvider"
_COMPOSITE_CLASS = "CompositeProvider"
# 클라우드 제공자 클래스 전부 — 학생 대면 앱이 이 중 무엇이든 직접 만들면 셀렉터를 우회한다.
# anthropic만 보면 `OpenRouterProvider()` 하드코딩(= 셀렉터를 무시한 채 좌석 고정)이 통과한다.
_CLOUD_PROVIDER_CLASSES: tuple[str, ...] = (
    "AnthropicProvider",
    "OpenRouterProvider",
    "DeepSeekProvider",
)


def _calls_named(source: str, name: str) -> int:
    """AST에서 `name(...)` 호출 횟수 — 주석·문자열·docstring은 세지 않는다."""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    )


# ===========================================================================
# ① 기본값 = openrouter — ARCH-64 컷오버(ARCH-55 "기본 핀 불변" 조항 번복)
# ===========================================================================


def test_default_cloud_provider_is_openrouter() -> None:
    """기본 클라우드 좌석은 `openrouter`다 — **ARCH-55 "기본 핀 불변" 조항의 번복**(ARCH-64).

    왜 바뀌었나: 2026-09-21 Kiki 지시("학생 대면까지 한 번에" → "학생대면도 오픈라우터로 전환")가
    전환의 목적지를 확정했고, 같은 날 게이트 `G-cloud-mid-seat-cutover`가 판정 ①(저작+학생 대면
    동시 컷오버)로 clear됐다. 종전 이 테스트(`test_default_cloud_provider_is_anthropic`)는 ARCH-55
    판정문의 "선택지를 넓힌 것이지 기본값을 옮긴 것이 아니다"를 동결했다 — 그 판정문은 지우지
    않고 번복 표기를 덧붙였다(`docs/ops/arch55_provider_battle_smoke_runbook.md` 「채택 판정」).

    이 단언이 red라면 누군가 기본값을 다시 옮긴 것이다. 그것도 코드 변경이 아니라 판정이다 —
    새 판정의 근거(게이트·결정 로그)를 이 docstring과 함께 고친다. 특히 `anthropic`으로 되돌리면
    ARCH-66(2026-09-24~12-31 Anthropic API 중단) 기간 내내 클라우드 결정이 전부 오류가 된다.
    """
    assert Settings.model_fields["cloud_provider"].default == "openrouter"


def test_factory_returns_openrouter_under_default_settings() -> None:
    """정본화가 아니라 *동작* — 기본 설정에서 팩토리가 실제로 OpenRouter 좌석을 만든다."""
    from whymath_backend.l3.providers.openrouter import OpenRouterProvider

    provider = build_cloud_provider(Settings(jwt_secret_key="x" * 32))  # type: ignore[arg-type]
    assert isinstance(provider, OpenRouterProvider)


def test_anthropic_selector_value_still_builds_anthropic_seat() -> None:
    """기본값이 옮겨졌어도 `anthropic` 값은 여전히 그 좌석을 만든다 — 분기 소실 방지.

    기본값 전환이 셀렉터의 선택지를 줄인 것이 아니라는 확인이다(ARCH-63 재개 뒤 2차 좌석이
    이 분기를 쓴다).
    """
    from whymath_backend.l3.providers.anthropic import AnthropicProvider

    settings = Settings(jwt_secret_key="x" * 32, cloud_provider="anthropic")  # type: ignore[arg-type]
    assert isinstance(build_cloud_provider(settings), AnthropicProvider)


@pytest.mark.parametrize(
    ("selector", "module", "class_name"),
    [
        ("openrouter", "openrouter", "OpenRouterProvider"),
        ("deepseek", "deepseek", "DeepSeekProvider"),
    ],
)
def test_factory_honours_each_selector_value(selector: str, module: str, class_name: str) -> None:
    """셀렉터 값마다 그 좌석이 실제로 나온다 — 분기가 조용히 anthropic으로 접히지 않는다."""
    import importlib

    settings = Settings(jwt_secret_key="x" * 32, cloud_provider=selector)  # type: ignore[arg-type]
    expected = getattr(
        importlib.import_module(f"whymath_backend.l3.providers.{module}"), class_name
    )
    assert isinstance(build_cloud_provider(settings), expected)
    assert cloud_provider_name(settings) == selector  # ⑤ 작동 신호가 좌석을 말한다


# ===========================================================================
# ② 집행 지점 — 저작 경로가 실제로 팩토리를 경유하는가 (AST 전수)
# ===========================================================================


def test_authoring_sites_build_cloud_provider_through_the_factory() -> None:
    """저작 경로 전건이 팩토리를 호출하고 `AnthropicProvider()`를 직접 만들지 않는다."""
    missing_factory: list[str] = []
    hardcoded: list[str] = []

    for rel in _AUTHORING_SITES:
        source = (_BACKEND_SRC / rel).read_text(encoding="utf-8")
        if _calls_named(source, _FACTORY_FUNC) == 0:
            missing_factory.append(rel)
        if _calls_named(source, _HARDCODED_CLASS) > 0:
            hardcoded.append(rel)

    assert not missing_factory, (
        f"저작 경로인데 {_FACTORY_FUNC}()를 부르지 않는다: {missing_factory} — "
        "클라우드 좌석이 이 파일에 박히면 셀렉터가 그 파일에는 닿지 않는다(ARCH-55 채택 경로를 "
        "고를 수 없게 된다)."
    )
    assert not hardcoded, (
        f"저작 경로에 {_HARDCODED_CLASS}() 직접 생성이 되살아났다: {hardcoded} — "
        f"{_FACTORY_FUNC}()로 바꾸라. 기본값이 anthropic이라 동작은 같아 보이지만, "
        "셀렉터를 openrouter로 둬도 이 자리만 anthropic으로 도는 조용한 불일치가 생긴다."
    )


def test_authoring_sites_all_exist() -> None:
    """④ 스캔 0건은 실패 — 경로가 옮겨졌는데 가드가 공허하게 통과하는 것을 막는다."""
    for rel in _AUTHORING_SITES:
        assert (_BACKEND_SRC / rel).is_file(), f"저작 경로가 사라졌다: {rel} — 목록을 갱신하라"
    assert len(_AUTHORING_SITES) >= 7, "저작 경로 목록이 비정상적으로 짧다(가드 무력화 의심)"


# ===========================================================================
# ③ 학생 대면도 팩토리 경유 — ARCH-57 "제외 동결"의 반대 방향 가드 (ARCH-64)
# ===========================================================================


def _composite_cloud_arguments(source: str) -> list[ast.expr | None]:
    """`CompositeProvider(...)` 호출마다 `cloud=` 인자 식을 모은다(없으면 None).

    좌석 조립 **위치**를 보는 것이 요점이다 — 파일 어딘가에 팩토리 호출이 *있다*는 것만으로는
    그 결과가 실제로 cloud 슬롯에 꽂히는지 알 수 없다(팩토리를 부르고 버린 뒤 옆에서
    `AnthropicProvider()`를 꽂아도 "호출 있음"은 참이다).
    """
    tree = ast.parse(source)
    found: list[ast.expr | None] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == _COMPOSITE_CLASS
        ):
            cloud = next((kw.value for kw in node.keywords if kw.arg == "cloud"), None)
            found.append(cloud)
    return found


def test_student_facing_app_assembles_cloud_seat_through_the_factory() -> None:
    """`app.py`의 학생 대면 좌석은 **반드시** `build_cloud_provider()`로 조립된다 (ARCH-64 ③).

    이 테스트의 전신(`test_student_facing_app_does_not_use_the_selector`)은 정반대를 동결했다 —
    "학생 대면은 셀렉터를 타지 않는다". 그것은 미구현이 아니라 판정이었고, docstring이 순서를
    못박았다: "판정을 먼저 내리고 → 게이트를 clear하고 → 그 근거로 이 테스트를 고친다". 그 순서가
    지켜졌다: 2026-09-21 Kiki 지시("학생대면도 오픈라우터로 전환") → 같은 날 게이트
    `G-cloud-mid-seat-cutover` clear(판정 ① 저작+학생 대면 동시 컷오버 · `backlog/gates.yaml`)
    → 이 갱신(ARCH-64). ARCH-56의 acceptance 재정의("차단 판정"→"운영 지표 기준선")도 같은 판정의
    범위다(게이트 evidence).

    가드를 **무력화하지 않고 뒤집었다** — 여전히 좌석 조립 위치를 본다:
      ⓐ `CompositeProvider(...)` 호출이 1건 이상 있다(스캔 0건 = 가드 공허 = 실패).
      ⓑ 그 호출 전부의 `cloud=` 인자가 `build_cloud_provider(...)` 호출 그 자체다 — 변수·
         조건식·다른 클래스를 거치면 셀렉터가 좌석에 닿는지 AST로 증명할 수 없다.
      ⓒ `app.py` 어디에도 클라우드 제공자 클래스 직접 생성이 없다(anthropic만이 아니라 3종 전부 —
         `OpenRouterProvider()` 고정도 셀렉터 우회다).

    2차 좌석이 없다는 것(2026-09-28 Kiki 결정)은 이 가드가 아니라
    `test_cloud_mid_seat_cutover.py`가 동결한다.
    """
    source = (_BACKEND_SRC / _STUDENT_FACING).read_text(encoding="utf-8")

    cloud_args = _composite_cloud_arguments(source)
    assert cloud_args, (
        f"{_STUDENT_FACING}에서 {_COMPOSITE_CLASS}(...) 호출을 하나도 찾지 못했다 — 학생 대면 좌석 "
        "조립이 옮겨졌다면 이 가드도 그 자리를 보도록 갱신하라(스캔 0건은 통과가 아니다)."
    )
    not_via_factory = [
        ast.unparse(arg) if arg is not None else "<cloud= 없음>"
        for arg in cloud_args
        if not (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == _FACTORY_FUNC
        )
    ]
    assert not not_via_factory, (
        f"{_STUDENT_FACING}의 {_COMPOSITE_CLASS} cloud 슬롯이 {_FACTORY_FUNC}()를 거치지 않는다: "
        f"{not_via_factory} — 학생 대면 좌석이 셀렉터와 갈라진다(저작은 openrouter인데 학생 "
        "대면만 다른 좌석이 되는 불일치). ARCH-64 게이트 G-cloud-mid-seat-cutover 판정 ① 위반."
    )
    hardcoded = {name: _calls_named(source, name) for name in _CLOUD_PROVIDER_CLASSES}
    hardcoded = {name: count for name, count in hardcoded.items() if count}
    assert not hardcoded, (
        f"{_STUDENT_FACING}에서 클라우드 제공자 직접 생성이 발견됐다: {hardcoded} — "
        f"{_FACTORY_FUNC}()로 바꾸라. 직접 생성은 셀렉터를 우회해 좌석을 코드에 고정한다."
    )


def test_unknown_selector_raises_instead_of_falling_back_to_anthropic() -> None:
    """알 수 없는 좌석 이름은 **예외**다 — 기본 좌석으로 조용히 접히지 않는다.

    `Literal`에 값을 늘리고 팩토리 분기를 안 붙이는 것이 현실적인 실수 경로인데, 그때 else로
    anthropic을 돌려주면 새 좌석을 고른 사람이 기본 좌석을 받고도 그 사실을 모른다
    (CLAUDE.md 「침묵 실패 금지」). `assert`가 아니라 `raise`인 것도 계약이다 — `python -O`가
    단언을 제거하면 그 침묵이 배포에서만 되살아난다.

    `Settings`가 Literal을 강제하므로 정상 경로로는 이 값이 올 수 없다. 그래서 검증 밖에서
    값을 밀어 넣는다(모델 우회) — 실제 사고 형태(코드가 늘어난 상태)의 대역이다.
    """

    class _UnknownSeat:
        cloud_provider = "gemini"  # Literal에 없는 값 — 분기 미추가 상태의 대역

        def __getattr__(self, item: str) -> object:  # pragma: no cover - 방어
            raise AttributeError(item)

    with pytest.raises(ValueError, match="알 수 없는 cloud_provider"):
        build_cloud_provider(_UnknownSeat())  # type: ignore[arg-type]
