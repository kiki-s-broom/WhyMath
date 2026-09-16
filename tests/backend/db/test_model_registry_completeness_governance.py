"""모델 레지스트리 전수성 거버넌스 — `db/models/__init__.py`가 정말 *모든* 테이블을 등록하는가 (ARCH-09).

`whymath_backend/db/models/__init__.py`는 자기 docstring에 **"모든 테이블을 import해
`Base.metadata`에 등록한다"**고 적고, 저장소의 두 소비자가 그 약속에 의존한다:

1. **문자열 FK 해소** — `concept.current_published_version_id`처럼 `sa.ForeignKey("<표>.<열>")`
   형태로 선언된 FK는 *같은 `MetaData`에 대상 표가 있을 때만* 해소된다. 없으면 SQLAlchemy가
   `NoReferencedTableError`를 던진다.
2. **alembic autogenerate** — `alembic/env.py`의 `target_metadata = Base.metadata`. 등록되지
   않은 표는 "DB에는 있는데 메타데이터에 없는 표"로 보여 **drop 제안**이 나간다.

**왜 전체 스위트로는 이 회귀를 잡을 수 없는가(이 가드가 존재하는 이유)**: 등록이 빠져도 *다른
테스트가 그 모듈을 직접 import하면* 부작용으로 메타데이터가 채워져 초록이 된다. 그래서 전체
스위트는 통과하고 **좁은 선택만 실패**한다 — 실제로 그랬다(2026-09-14 CI run 34898025896:
`e2e-nightly` 잡은 `NoReferencedTableError`로 red, 같은 회차 전체 스위트 잡은 success).

그래서 이 가드는 **다른 테스트의 import 부작용에 의존하지 않는다** — 깨끗한 하위 프로세스에서
①레지스트리만 import한 뒤의 표 집합과 ②패키지의 모든 모듈을 import한 뒤의 표 집합을 각각 구해
차집합을 본다. 이 파일 하나만 선택해 돌려도 성립한다.

**AST로 `__tablename__`을 훑지 않는 이유**: 표기 변형(상수가 아닌 표현식·`__table__` 직접 지정·
믹스인 상속)에서 조용히 뚫린다. 금지 패턴 열거가 아니라 **구성된 결과**(실제 등록된 표)를 본다
(CLAUDE.md 2026-09-01 ①).
"""

from __future__ import annotations

import json
import subprocess
import sys

# 하위 프로세스에서 실행할 프로브 — 표 집합 두 개를 구해 JSON 한 줄로 낸다.
#   ① registry: `whymath_backend.db.models`만 import했을 때 등록된 표
#   ② full:     그 패키지의 *모든* 모듈을 import했을 때 등록된 표
# 두 집합의 차이가 곧 "파일은 있는데 레지스트리가 안 부르는" 표다.
_PROBE = """
import importlib, importlib.util, json, pkgutil, sys

import whymath_backend.db.models as models_pkg
from whymath_backend.db.base import Base

registry = sorted(Base.metadata.tables)

modules = []
for info in pkgutil.iter_modules(models_pkg.__path__):
    modules.append(info.name)
    importlib.import_module("whymath_backend.db.models." + info.name)

# 양성 대조군(선택) — 레지스트리가 결코 부르지 않는 모듈을 파일 경로로 하나 더 import한다.
# 이것이 `full`에 나타나지 않으면 델타 기전 자체가 죽은 것이다(변별력 검사용).
if len(sys.argv) > 1:
    spec = importlib.util.spec_from_file_location("_arch09_control", sys.argv[1])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

print(json.dumps({
    "registry": registry,
    "full": sorted(Base.metadata.tables),
    "modules": sorted(modules),
}))
"""


def _probe(control_module: str | None = None) -> dict[str, list[str]]:
    """깨끗한 하위 프로세스에서 프로브를 실행해 결과를 돌려준다(부작용 격리).

    `control_module`을 주면 레지스트리가 결코 부르지 않는 모듈을 파일 경로로 추가 import한다 —
    그 표가 `full - registry`에 나타나야 델타 기전이 살아 있다는 뜻이다.
    """
    cmd = [sys.executable, "-c", _PROBE]
    if control_module is not None:
        cmd.append(control_module)
    out = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, (
        "레지스트리 프로브가 실패했다 — 측정 실패이지 '이상 없음'이 아니다.\n"
        f"stderr(뒤 2000자):\n{out.stderr[-2000:]}"
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_every_model_module_is_registered_by_the_package_initializer() -> None:
    """모델 파일이 선언한 표는 전부 `db/models/__init__.py` 경유로 등록돼야 한다.

    실패 시 처방: 빠진 모듈의 import 1줄을 `db/models/__init__.py`에 추가한다
    (다른 모델과 같은 관례 — `__all__`에도 함께 적는다).
    """
    probe = _probe()
    registry = set(probe["registry"])
    full = set(probe["full"])

    # 스캔 0건은 통과가 아니라 실패다 — 대상을 못 찾은 전수 가드는 공허하게 초록을 낸다
    # (CLAUDE.md 2026-09-01 ④). 실측 하한: 모델 모듈 52개 · 등록 표 80개(2026-09-15).
    assert (
        len(probe["modules"]) >= 40
    ), f"모델 모듈 스캔이 비정상적으로 적다: {len(probe['modules'])}건"
    assert len(registry) >= 60, f"레지스트리 등록 표가 비정상적으로 적다: {len(registry)}건"

    unregistered = sorted(full - registry)
    assert not unregistered, (
        "레지스트리에 등록되지 않은 표가 있다 — 좁은 테스트 선택에서 문자열 FK가 해소되지 않고, "
        "alembic autogenerate가 실재 테이블을 drop 제안한다.\n"
        f"  미등록: {unregistered}\n"
        "  처방: 해당 모듈의 import를 src/backend/whymath_backend/db/models/__init__.py 에 추가."
    )


def test_probe_actually_detects_an_unregistered_table(tmp_path) -> None:
    """가드 자신의 변별력 — 프로브가 *미등록 표를 실제로 검출하는가*(양성 대조군).

    `registry <= full`만 단언하면 두 집합이 **항상 같도록** 프로브가 망가져도 통과한다(실측:
    그 형태의 뮤테이션 M5가 초판에서 생존했다). 그래서 레지스트리가 결코 부르지 않는 모듈을
    하나 만들어 프로브에 물리고, 그 표가 `full - registry`에 **나타나는지**를 본다 — 나타나지
    않으면 위 테스트는 어떤 회귀에서도 초록인 위장이다.
    """
    control = tmp_path / "arch09_control_model.py"
    control.write_text(
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "from whymath_backend.db.base import Base\n"
        "\n"
        "class _Arch09ControlModel(Base):\n"
        '    """레지스트리 밖 대조군 — 이 표가 델타에 안 잡히면 프로브가 죽은 것이다."""\n'
        '    __tablename__ = "_arch09_control_table"\n'
        "    id: Mapped[int] = mapped_column(primary_key=True)\n",
        encoding="utf-8",
    )
    probe = _probe(control_module=str(control))
    delta = set(probe["full"]) - set(probe["registry"])

    assert "_arch09_control_table" in delta, (
        "대조군 표가 델타에 잡히지 않았다 — 프로브가 `full`을 전 모듈 import *이후*에 구하고 "
        "있지 않다는 뜻이며, 그렇다면 미등록 검출 테스트는 위장이다.\n"
        f"  delta={sorted(delta)}"
    )
    # 대조군 말고 다른 것이 섞이면 레지스트리가 실제로 미등록 표를 갖고 있다는 뜻 — 위 테스트가 잡는다.
    assert set(probe["registry"]) <= set(
        probe["full"]
    ), "전 모듈 import 집합이 레지스트리 집합을 덮지 않는다 — 두 단계가 같은 MetaData를 보고 있지 않다."
