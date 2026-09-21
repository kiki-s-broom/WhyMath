"""모델 패키지 `__init__`의 **등록 완전성** 동결 — autogenerate가 보는 것과 실재가 같은가.

왜 필요한가 (실측 사고 2026-09-16)
----------------------------------
`whymath_backend/db/models/__init__.py`의 docstring은 *"모든 테이블을 import해
`Base.metadata`에 등록한다"*고 못박고, `alembic/env.py`는 정확히 그 import 하나에 기대
`target_metadata`를 만든다(`env.py`: "이 import가 없으면 autogenerate가 테이블을 못 본다").

그런데 `EOS-49`가 `concept_version` 테이블과 `concept.current_published_version_id` FK를
추가하면서 **모델을 이 패키지에 등록하지 않았다.** 결과:

  - `import whymath_backend.db.models` → 78테이블(전수 walk는 79) — `concept_version` 부재.
  - 그 상태로 autogenerate를 돌리면 **실재하는 테이블을 삭제 대상으로 본다**
    (metadata에 없고 DB에는 있으므로 `op.drop_table('concept_version')`).
  - `Concept`만 import한 소비처는 FK 타깃을 못 찾아 `NoReferencedTableError`로 죽는다
    (이 테스트가 생긴 계기 — 통합테스트 5건이 그 예외로 전부 error였다).

**왜 기존 동결이 못 잡았나**: `test_canonical_entity_model_freeze.py`는 `pkgutil`로 패키지의
*모든 모듈*을 직접 walk해 적재한다("부분 적재면 측정이 새는다"는 옳은 판단이다). 그래서 수를
정확히 세지만, 바로 그 이유로 **`__init__`이 불완전해도 초록**이다. 그 테스트는 "모델이
존재하는가"를 묻고, 이 테스트는 "**정본 import 경로가 그것을 끌어오는가**"를 묻는다 —
alembic이 쓰는 것은 후자다.

왜 서브프로세스인가 (이 파일의 설계 핵심)
------------------------------------------
`Base.metadata`는 **프로세스 전역**이다. 같은 스위트의 다른 테스트가 먼저 모델 모듈을
import하면 이 검사는 "이미 다 등록된 상태"를 보고 **언제나 통과한다** — 그리고 pytest-randomly
(OPS-09)가 순서를 섞으므로 그 오염은 실행마다 달라진다. 즉 in-process로 재면 정상 상태에서
초록인데 결함 상태에서도 초록인, 변별력 0의 검사가 된다(CLAUDE.md "변별력 없는 검증 스텝 금지").

그래서 두 수집을 **각각 새 인터프리터**에서 돌린다. 느리지만(≈2회 import) 이 검사는 격리
없이는 의미가 없다.
"""

from __future__ import annotations

import json
import subprocess
import sys

_VIA_INIT = """
import json
import whymath_backend.db.models  # noqa: F401  (정본 경로 — alembic env.py와 동일)
from whymath_backend.db.base import Base
print(json.dumps(sorted(Base.metadata.tables)))
"""

_VIA_WALK = """
import importlib, json, pkgutil
import whymath_backend.db.models as pkg
from whymath_backend.db.base import Base
for m in pkgutil.iter_modules(pkg.__path__):
    importlib.import_module(f"whymath_backend.db.models.{m.name}")
print(json.dumps(sorted(Base.metadata.tables)))
"""


def _tables(script: str) -> set[str]:
    """새 인터프리터에서 수집 — 전역 metadata 오염을 배제한다(모듈 docstring 참조)."""
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"수집 서브프로세스 실패(측정 불가):\n{proc.stderr[-2000:]}"
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_package_import_alone_registers_every_model_table() -> None:
    """`__init__`만 import해도 전 모델이 등록되는가 — alembic이 보는 것이 이것이다."""
    via_init = _tables(_VIA_INIT)
    via_walk = _tables(_VIA_WALK)

    missing = via_walk - via_init
    assert not missing, (
        f"모델 모듈에는 있는데 `db/models/__init__.py`가 끌어오지 않는 테이블: {sorted(missing)}. "
        "alembic env.py는 이 패키지 import 하나에만 기대므로, 등록되지 않은 테이블은 "
        "autogenerate에서 **삭제 대상**으로 보인다. `__init__`에 import와 `__all__` 항목을 더하라."
    )


def test_the_comparison_is_not_vacuous() -> None:
    """두 수집이 실제로 테이블을 찾았는가 — 0건끼리 비교하면 언제나 통과한다."""
    assert len(_tables(_VIA_WALK)) > 50, "전수 walk가 모델을 거의 못 찾았다 — 측정 실패"
    assert len(_tables(_VIA_INIT)) > 50, "정본 경로가 모델을 거의 못 찾았다 — 측정 실패"


def test_concept_version_is_registered_by_the_canonical_import() -> None:
    """회귀 표적 — EOS-49가 빠뜨렸던 바로 그 테이블(2026-09-16 실측).

    일반 검사(위)가 이미 덮지만, 이 건은 **FK 타깃**이라 빠지면 `Concept`를 import하는 모든
    소비처가 죽는다. 사고를 이름으로 남겨 다음 세션이 경위를 찾을 수 있게 한다.
    """
    assert "concept_version" in _tables(_VIA_INIT)
