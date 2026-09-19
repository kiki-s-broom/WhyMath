"""[P-15] 페르소나 3인 완주 하네스의 **야간 배선 실재성** 동결.

왜 이 파일이 따로 있는가
------------------------
`tests/backend/api/test_persona_three_path_completion.py`는 실 PG가 있어야 판정한다. PG가
없으면 판정하지 않고 **skip**하고, pytest는 skip에 exit 0을 낸다 — 즉 *아무것도 검증하지 않은
실행*이 초록으로 보인다. 그래서 "ci.yml에 스텝을 적었다"는 것만으로는 이 판정이 돈다고 말할 수
없다(OPS-03/08/11 선례 — "저장소에 존재함"과 "돌아감"은 다르다).

판정 함수는 **P-11 배선 가드의 것을 그대로 빌려 쓴다**(재구현 0). 그쪽
(`test_p11_chain_nightly_wiring.py`)의 `real_pg_violations`와, 그것이 다시 앵커 가드에서
빌려 온 `anchor_wiring_violations`는 둘 다 `test_path`로 매개화된 순수 함수이고 변별력이 이미
주입으로 봉인돼 있다. 여기서 다시 구현하면 같은 계약의 판정기가 둘이 되고, 한쪽만 고쳐지는
순간 조용히 어긋난다. 이 파일의 기여는 **대상 경로를 P-15 하네스로 바꿔 같은 계약을 거는 것**
하나다.

축은 P-11과 동일하게 다섯이다: ①대상 파일 실재 ②③④ schedule 잡에 fail-closed·
`python -m pytest`로 배선 ⑤ 그 잡이 실 PG를 준다(postgres service + `WHYMATH_RUN_INTEGRATION`
+ DSN). 빌려 온 함수의 변별력은 그쪽 파일이 합성 주입으로 매번 재확인하므로 여기서는 *이
경로에 대해* 위반 0인지만 본다 — 다만 판정기가 살아 있다는 것 자체는 아래 음성 대조군이
확인한다(빌려 온 이름이 무해한 스텁으로 바뀌면 이 파일도 함께 빨강이 된다).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Any

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: 배선 대상 — P-15 페르소나 3인 완주 하네스(실 PG 필요).
PERSONA_TEST_PATH = "tests/backend/api/test_persona_three_path_completion.py"

_P11_PATH = pathlib.Path(__file__).with_name("test_p11_chain_nightly_wiring.py")
#: 빌려 쓰는 판정기 계약 — 이름이 바뀌면 수집 단계에서 지목하며 실패한다(조용한 표류 방지).
_P11_BORROWED = ("real_pg_violations", "_wiring_violations")


def _load_p11_guard() -> ModuleType:
    """P-11 배선 가드를 파일 경로로 적재하고 빌려 쓰는 이름을 검사한다."""
    if not _P11_PATH.exists():
        raise AssertionError(
            f"P-11 배선 가드가 없다: {_P11_PATH}. 이 파일은 그 판정 함수를 재사용한다 — "
            "옮겨졌으면 이 경로를 함께 고친다."
        )
    spec = importlib.util.spec_from_file_location("_p11_wiring_guard", _P11_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"P-11 배선 가드 스펙 생성 실패: {_P11_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    missing = [name for name in _P11_BORROWED if not hasattr(module, name)]
    if missing:
        raise AssertionError(
            f"P-11 배선 가드의 판정기가 사라졌다: {missing}. 이 파일이 그것을 재사용하므로 "
            "이름이 바뀌면 여기도 함께 고쳐야 한다."
        )
    return module


_P11 = _load_p11_guard()
_real_pg_violations = _P11.real_pg_violations
_wiring_violations = _P11._wiring_violations


def _load_workflow() -> dict[str, Any]:
    """ci.yml 파싱 — 못 읽거나 jobs가 비면 '통과'가 아니라 실패한다."""
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")
    return spec


def test_persona_harness_file_exists() -> None:
    """① 배선 대상이 실재한다 — 없으면 야간 스텝은 매일 '수집 0건 통과'가 된다."""
    target = _REPO_ROOT / PERSONA_TEST_PATH
    assert target.is_file(), (
        f"{target} 이(가) 없다 — ci.yml이 가리키는 페르소나 하네스가 사라지면 스텝은 조용히 "
        "초록이 된다(측정 실패가 통과로 위장되는 형태)."
    )


def test_persona_harness_is_wired_into_nightly_schedule() -> None:
    """②③④ schedule 잡에 fail-closed로·`python -m pytest`로 얹혀 있다."""
    violations = _wiring_violations(_load_workflow(), test_path=PERSONA_TEST_PATH)
    assert violations == [], "야간 배선 계약 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_persona_harness_job_actually_reaches_real_postgres() -> None:
    """⑤ 그 잡이 실 PG를 준다 — 배선의 실재와 배선의 *도달*은 다르다."""
    violations = _real_pg_violations(_load_workflow(), test_path=PERSONA_TEST_PATH)
    assert violations == [], "실 PG 도달 계약 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_borrowed_judges_are_not_vacuous_for_this_path() -> None:
    """음성 대조 — 빌려 온 판정기가 *이 경로에 대해서도* 실제로 위반을 낸다.

    빌려 쓰는 함수는 그쪽 파일이 합성 주입으로 변별력을 봉인하지만, 그 봉인은 P-11 경로에
    대한 것이다. `test_path` 인자가 어딘가에서 무시되면 이 파일의 세 단언은 P-11 배선을 보고
    초록을 내면서도 P-15에 대해서는 **아무것도 검증하지 않는다**. 존재하지 않는 경로를 넣어
    위반이 나오는지 확인해 그 상태를 배제한다.
    """
    spec = _load_workflow()
    absent = "tests/backend/api/test_p15_path_that_does_not_exist.py"
    assert _wiring_violations(spec, test_path=absent) != []
    assert _real_pg_violations(spec, test_path=absent) != []
