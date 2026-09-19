"""CORE 배정 모듈의 수학 어휘 **ratchet 게이트** — 계획서 200 §5 금지어 축의 집행 (EOS-04).

왜 필요한가
-----------
계획서 200 §5는 *"Architecture 문서에만 쓰면 반드시 다시 침범한다 — CI에서 검사해야 한다"*고
적고, Core 내부에 `quadratic`·`polynomial`·`geometry`·`latex`·`sympy`·`desmos`·
`equation_solver`가 등장하면 경고하라고 든다.

저장소에는 그 어휘를 **세는 계측기**가 이미 있었다(`eos_core_adapter_boundary_scan.py`의
`MATH_TOKEN_RE`·`어휘/kloc` 지표). 그러나 그 스크립트는 스스로 *"게이트가 아니라 계측기"*라
적고 위반으로 exit 1을 내지 않으며, 실측(2026-09-16) 결과 `.github/` 어디에서도 호출되지
않았다. 즉 **숫자는 있는데 아무도 그 숫자가 오르는 것을 막지 않았다.**

이 파일이 그 집행 지점이다 — `tests/infra`는 `infra-contracts` 잡이 매 PR 돌린다.

왜 총합이 아니라 모듈별인가
---------------------------
총합 하나로 재면 **한 모듈이 줄고 다른 모듈이 느는 것**을 못 본다(합이 같으면 통과한다).
경계 침범은 언제나 특정 모듈에서 일어나므로 키를 모듈로 둔다. 그래야 RED 메시지가 "어디를
보라"를 말한다.

ratchet 방향 — 늘면 RED, **줄어도 RED**
---------------------------------------
줄었을 때도 실패시키는 이유는 `import-linter`의 `unmatched_ignore_imports_alerting`이 같은
일을 하는 이유와 같다: 유예를 **날짜가 아니라 기계가 만료**시켜야 한다. 실제로 이 저장소는
`EOS-89`가 합성 루트 경유 간선 2건을 없앴을 때 그 기계가 "이 줄을 지워라"라고 말해 줬다
(`src/backend/pyproject.toml` 주석). 사람이 기억해서 기준선을 내리는 방식은 반드시 썩는다.

이 게이트가 잡지 **않는** 것 (있는 척 금지)
-------------------------------------------
- **어휘가 코드인지 산문인지 구별하지 않는다.** `MATH_TOKEN_RE`는 파일 텍스트를 훑으므로
  docstring·주석의 언급도 센다. 아래 기준선의 상당수가 실제로 산문이며, 어느 건이 그런지는
  기준선 주석이 건별로 적는다. 코드 *식별자* 축을 겨냥하는 검사는 별도로 있다 —
  `test_eos_core_boundary_probe.py`(리터럴 비교·문자열 상수)와
  `test_eos_opaque_payload_gate.py`(payload 값 해석).
- **배정이 옳은지 보지 않는다.** 어떤 모듈이 CORE인가는 `BOUNDARY_MAP`이 정본이고 사람이
  정한다. 이 게이트는 그 배정을 전제로 *변화*만 잰다.
- **import 방향을 보지 않는다.** 그 축은 `EOS-67` import-linter 계약 2건이 맡는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "eos_core_adapter_boundary_scan.py"

# ──────────────────────────────────────────────────────────────────────
# 기준선 — CORE 배정 모듈별 수학 어휘 적중 수 (실측 2026-09-16 · main 2520a27c)
#
# 합계 74 / 28모듈. 새 모듈이 어휘를 갖거나 기존 모듈의 수가 오르면 RED.
# 줄면 "기준선을 내려라"로 RED(유예의 기계 만료).
#
# 큰 값 몇 건의 성격(왜 유예되는가):
#   · l3.pedagogy.slot_generator(10) — 슬롯 검증이 어댑터 능력을 주입받는 자리. 경유 간선
#     이력이 있던 모듈이며 EOS-89가 push 전환으로 간선을 없앴다.
#   · l4.solution_coaching(8) — pyproject `ignore_imports`에 남은 **유일한** 경유 간선의
#     출발점(EOS-86). 재확인 지점 G1(2026-09-27).
#   · l3.solution_path(6) / l4.misconception.*(5·4·3·2) — 수학 풀이·오개념 도메인 산문.
#   · schema.visualization(2) · l3.visualization(2) — **전부 docstring 산문**이며
#     "렌더는 D3/Plotly/Desmos가 한다"고 설명하는 문장이다(EOS-04가 desmos 어휘를
#     추가하며 +3한 자리 — 어휘 추가로 오른 분을 조용히 묻지 않고 여기 적는다).
# ──────────────────────────────────────────────────────────────────────
CORE_MATH_VOCAB_BASELINE: dict[str, int] = {
    "api.study": 1,
    "l1.embedding_primitives": 1,
    "l3.cross_verify": 1,
    "l3.pedagogy.example_generator": 4,
    "l3.pedagogy.explanation_checker": 5,
    "l3.pedagogy.prescreen": 1,
    "l3.pedagogy.review": 3,
    "l3.pedagogy.slot_generator": 10,
    "l3.providers.anthropic": 1,
    "l3.providers.ollama": 1,
    "l3.queue.tasks": 1,
    "l3.render.adapter": 1,
    "l3.render.adapters": 2,
    "l3.render.dsl": 2,
    "l3.solution_path": 6,
    "l3.visualization": 2,
    "l3.viz_eval": 1,
    "l4.misconception.catalog": 5,
    "l4.misconception.diagnose": 4,
    "l4.misconception.distractor": 3,
    "l4.misconception.models": 2,
    "l4.scene_generation": 1,
    "l4.solution_coaching": 8,
    "l5": 2,
    "schema.analytics_event": 1,
    "schema.concept": 2,
    "schema.subject_adapter": 1,
    "schema.visualization": 2,
}

# 계획서 200 §5가 열거한 7어휘 — 정규식이 이것들을 실제로 담고 있는지 대조한다.
PLAN200_VOCABULARY = (
    "quadratic",
    "polynomial",
    "geometry",
    "latex",
    "sympy",
    "desmos",
    "equation_solver",
)


def _load_scan_module() -> Any:
    name = "_eos_boundary_scan_ratchet"
    spec = importlib.util.spec_from_file_location(name, _SCAN_SCRIPT)
    assert spec is not None and spec.loader is not None, f"스캔 스크립트 로드 불가: {_SCAN_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _core_vocab_counts(module: Any | None = None) -> dict[str, int]:
    """CORE 배정 모듈의 어휘 적중 수 — 0건 모듈은 빼고 돌려준다."""
    module = module or _load_scan_module()
    facts, errors = module.scan(_REPO_ROOT / module.DEFAULT_SOURCE, lambda *_: None)
    assert not errors, f"스캔 오류 {len(errors)}건 — 측정 실패를 통과로 읽지 않는다: {errors[:3]}"
    # 스캔 0건은 실패다 — 대상을 못 찾은 전수 검사는 공허하게 통과한다.
    assert len(facts) > 300, f"스캔 대상이 너무 적다({len(facts)}) — 측정이 성립하지 않았다"
    return {f.module: f.math_tokens for f in facts if f.verdict == "CORE" and f.math_tokens > 0}


def test_plan200_vocabulary_is_actually_in_the_regex() -> None:
    """계획서 §5의 7어휘가 정규식에 실재하는가 — 어휘가 빠지면 게이트는 그 축을 못 본다.

    `desmos`·`equation_solver`는 2026-09-16까지 빠져 있었다. 목록에 있다고 정규식이 그것을
    본다는 뜻이 아니므로, 열거가 아니라 **매칭**으로 확인한다.
    """
    pattern = _load_scan_module().MATH_TOKEN_RE
    missing = [word for word in PLAN200_VOCABULARY if not pattern.search(f"x {word} y")]
    assert not missing, f"계획서 200 §5 어휘가 정규식에 없다: {missing}"


def test_core_math_vocabulary_does_not_grow() -> None:
    """CORE 모듈의 수학 어휘가 늘면 RED — 계획서 200 §5의 집행 지점."""
    observed = _core_vocab_counts()
    grown = {
        mod: (CORE_MATH_VOCAB_BASELINE.get(mod, 0), n)
        for mod, n in observed.items()
        if n > CORE_MATH_VOCAB_BASELINE.get(mod, 0)
    }
    assert not grown, (
        "CORE 배정 모듈의 수학 어휘가 늘었다(기준선 → 실측): "
        f"{grown}. Core는 과목 의미론을 모르는 구역이다 — 어댑터로 옮기거나, "
        "산문 언급이라 무해하면 CORE_MATH_VOCAB_BASELINE에 근거와 함께 올린다."
    )


def test_core_math_vocabulary_baseline_is_ratcheted_down_when_it_shrinks() -> None:
    """줄었는데 기준선이 그대로면 RED — 유예를 사람 기억이 아니라 기계가 만료시킨다."""
    observed = _core_vocab_counts()
    if observed != CORE_MATH_VOCAB_BASELINE:
        shrunk = {
            mod: (base, observed.get(mod, 0))
            for mod, base in CORE_MATH_VOCAB_BASELINE.items()
            if observed.get(mod, 0) < base
        }
        if shrunk:
            pytest.fail(
                f"CORE 수학 어휘가 줄었다(기준선 → 실측): {shrunk}. "
                f"CORE_MATH_VOCAB_BASELINE을 실측값으로 내려라: {observed}"
            )


def test_scan_reports_a_real_measurement_not_an_empty_one() -> None:
    """측정기가 빈 결과를 돌려주면 위 두 게이트는 '비교 대상 0건'으로 조용히 통과한다.

    그 위장을 막기 위해 실측이 성립했다는 증거(알려진 배정·ADAPTER 밀도 우위)를 요구한다.
    CORE가 ADAPTER보다 어휘 밀도가 낮다는 것이 경계가 실재한다는 1차 신호다.
    """
    module = _load_scan_module()
    facts, errors = module.scan(_REPO_ROOT / module.DEFAULT_SOURCE, lambda *_: None)
    assert not errors
    summary = module.summarize(facts)
    core, adapter = summary["CORE"], summary["ADAPTER"]
    assert core["modules"] > 100 and adapter["modules"] > 10, f"배정 분포가 비었다: {summary}"
    core_density = core["math_tokens"] / core["loc"] * 1000
    adapter_density = adapter["math_tokens"] / adapter["loc"] * 1000
    assert adapter_density > core_density * 5, (
        f"ADAPTER({adapter_density:.1f}/kloc)가 CORE({core_density:.1f}/kloc)보다 "
        "수학 어휘가 뚜렷이 많지 않다 — 경계가 흐려졌거나 측정이 깨졌다"
    )
