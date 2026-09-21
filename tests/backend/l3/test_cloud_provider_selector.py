"""ARCH-57 — 클라우드 슬롯 셀렉터의 계약 동결 (정본화 ≠ 집행).

네 가지를 기계로 강제한다. 넷이 서로 다른 실패 모드를 겨냥하므로 하나로 합치지 않는다:

  ① **기본값 불변** — `cloud_provider` 기본이 `anthropic`이다. ARCH-55 채택 판정문이
     "선택지를 넓힌 것이지 기본값을 옮긴 것이 아니다"라고 적었고, 판정 기준 (d)(지연·가용성)가
     `ARCH-56`으로 보류 중이다. 이 기본값을 바꾸는 것은 코드 변경이 아니라 판정이며, 그래서
     산문이 아니라 여기서 막는다.
  ② **집행 지점** — 저작 경로가 실제로 팩토리를 경유한다. `AnthropicProvider()`를 다시
     하드코딩하면 red. **AST 전수 스캔**이며 문자열 금지목록이 아니다 — 별칭 import·줄바꿈·
     주석 같은 표기 변형에서 뚫리지 않게 *구성된 결과*를 본다(CLAUDE.md 「금지 패턴 열거 대신
     산출물 검사」).
  ③ **학생 대면 제외 동결** — `app.py`의 클라우드 슬롯은 셀렉터를 타지 **않는다**.
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

# 학생 대면 서빙 — 셀렉터를 타지 않는 것이 **의도**다(아래 ③ 참조).
_STUDENT_FACING = "app.py"

_FACTORY_FUNC = "build_cloud_provider"
_HARDCODED_CLASS = "AnthropicProvider"


def _calls_named(source: str, name: str) -> int:
    """AST에서 `name(...)` 호출 횟수 — 주석·문자열·docstring은 세지 않는다."""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    )


# ===========================================================================
# ① 기본값 불변 — 바꾸려면 ARCH-56 판정이 먼저다
# ===========================================================================


def test_default_cloud_provider_is_anthropic() -> None:
    """기본 클라우드 좌석은 `anthropic`이다 — ARCH-55 채택 판정의 "기본 핀 불변" 조항.

    이 단언이 red라면 누군가 기본값을 옮긴 것이고, 그 순간 (d) 지연·가용성이 **미판정인**
    구성이 저작 경로의 기본이 된다. 옮기려면 `ARCH-56-openrouter-availability-axis`를 먼저
    끝내고 그 판정을 근거로 이 테스트를 함께 고쳐야 한다.
    """
    assert Settings.model_fields["cloud_provider"].default == "anthropic"


def test_factory_returns_anthropic_under_default_settings() -> None:
    """정본화가 아니라 *동작* — 기본 설정에서 팩토리가 실제로 Anthropic 좌석을 만든다."""
    from whymath_backend.l3.providers.anthropic import AnthropicProvider

    provider = build_cloud_provider(Settings(jwt_secret_key="x" * 32))  # type: ignore[arg-type]
    assert isinstance(provider, AnthropicProvider)


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
# ③ 학생 대면 제외 동결 — 이 제외를 푸는 것은 게이트 발동이다
# ===========================================================================


def test_student_facing_app_does_not_use_the_selector() -> None:
    """`app.py`의 클라우드 슬롯은 셀렉터를 타지 않는다 — **이것은 미구현이 아니라 판정이다**.

    `G-arch56-availability-trigger`의 발동 조건 ⓐ는 "OpenRouter 경로가 학생 대면 또는 상시
    배치 트래픽을 받기로 결정된 때"다. `app.py`를 팩토리로 바꾸면 설정 한 줄로 학생 응답이
    OpenRouter로 나갈 수 있게 되고, 그것이 곧 그 결정의 실현이다. ARCH-55 판정 기준 (d)
    (지연·가용성)는 아직 보류이며 — 4회차 실측에서 429 실패율이 30%→15%→0%로 흔들렸고 p95가
    212초까지 갔다 — 미판정 구성을 학생에게 노출할 수 없다.

    **이 테스트를 푸는 것은 코드 판단이 아니라 Kiki 판정 사안이다.** 순서: ARCH-56을 끝내고
    → 게이트를 clear하고 → 그 근거로 이 테스트를 고친다. 반대 순서는 게이트를 우회하는 것이다
    (CLAUDE.md 「거부의 우회 금지」).
    """
    source = (_BACKEND_SRC / _STUDENT_FACING).read_text(encoding="utf-8")
    assert _calls_named(source, _FACTORY_FUNC) == 0, (
        f"{_STUDENT_FACING}가 {_FACTORY_FUNC}()를 부른다 — 학생 대면 경로가 셀렉터를 타게 됐다. "
        "이는 게이트 G-arch56-availability-trigger의 발동 조건 ⓐ에 해당하므로, 코드가 아니라 "
        "판정이 먼저다(위 docstring 순서 참조)."
    )
    assert _calls_named(source, _HARDCODED_CLASS) > 0, (
        f"{_STUDENT_FACING}에서 {_HARDCODED_CLASS}() 직접 생성이 사라졌다 — 학생 대면 좌석이 "
        "어디서 오는지 이 가드가 더는 알 수 없다. 좌석 조립이 옮겨졌다면 이 테스트도 그 자리를 "
        "보도록 갱신하라(무력화된 채 통과하면 안 된다)."
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
