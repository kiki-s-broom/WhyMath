"""런북 붙여넣기 블록 자기완결성 게이트의 **변별력 + 배선 실재** 동결 (HARN-115 ②③④⑥).

막는 것은 다섯이다.

① **무변별(red 축)** — 앞 블록의 변수·작업 폴더·DB 목적지에 기대는 블록이 통과하는 것.
   acceptance ③의 뮤테이션은 **정상 기준 블록**(`_REFERENCE`)에 가한다 — 그 블록이 모든 절을
   실제로 밟기 때문이다. 그 변수를 쓰지 않는 블록에서 정의만 지우면 정상적으로 GREEN이고
   그것은 검출 실패가 아니다(2026-09-18 실측: 주입 2건이 이 이유로 GREEN이었다).
② **무변별(green 축)** — 정상 블록이 red면 게이트가 아니라 개발 차단기다. 기준 블록과 사고
   당사자 런북(`g_skb01_resolution_remeasure_runbook.md`)이 통과해야 한다.
③ **판정기 자신의 경계** — 작은따옴표·백틱은 치환이 아니고, 큰따옴표·스플랫은 읽기이며,
   `$X = $X + 1`의 우변은 앞 블록의 값이다. DB 도달은 이름이 아니라 import 그래프로 정한다.
④ **유예의 침묵** — 만료·초과·과대·unmatched 유예가 조용히 통과하는 것.
⑤ **측정 실패의 위장** — 스캔 0건을 통과로 읽는 것 · 배선 없이 "있음"으로 선언하는 것.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_self_containment.py"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_BACKEND = _REPO_ROOT / "src" / "backend"
_INCIDENT_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "g_skb01_resolution_remeasure_runbook.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_runbook_self_containment", _SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load()


# ── 정상 기준 블록 — 모든 절을 밟는다(라벨·절대 cd·세션 변수·DB 목적지·psql·모듈 도달) ──
_REFERENCE = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$Py = "$Repo\src\backend\.venv\Scripts\python.exe"
cd "$Repo\src\backend"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"
& $Py -m whymath_backend.ops.db_host_reachability
& $Py -m alembic upgrade head
"ALEMBIC_EXIT=$LASTEXITCODE"
docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT version_num FROM alembic_version;"
& $Py -m whymath_backend.config
"""

_READ_HOST_OK = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
# ⚠ 이 블록만 단독으로 붙여넣는다 — 뒤 블록을 이어 붙이면 그 첫 줄이 입력값으로 삼켜진다.
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Answer = Read-Host "진행하려면 GO 를 입력하세요"
"ANSWER_LENGTH=$($Answer.Length)"
"""


def _block(body: str) -> list[str]:
    return body.strip("\n").splitlines()


def _axes(body: str, prose: list[str] | None = None) -> list[str]:
    """블록 하나의 위반 축 목록(경고 포함)."""
    block = sc.crb.Block(path=Path("fixture.md"), index=1, start_line=1, lines=_block(body))
    return [v.axis for v in sc.audit_block(block, sc.DbReach(_BACKEND), prose)]


def _mutate(body: str, old: str, new: str) -> str:
    """주입 실재 단언 — 앵커 1건 · 치환 후 원본과 다름(조용히 안 들어간 주입은 검출로 보인다)."""
    assert body.count(old) == 1, f"앵커가 1건이 아니다: {old!r}"
    mutated = body.replace(old, new)
    assert mutated != body, "주입이 들어가지 않았다"
    return mutated


# ═════════════════════════════════════════════════════════════════════════
# ② green 축
# ═════════════════════════════════════════════════════════════════════════
def test_reference_block_is_clean() -> None:
    """대조군 — 기준 블록이 red면 아래 뮤테이션의 RED는 아무 의미가 없다."""
    assert _axes(_REFERENCE) == []


def test_read_host_block_with_standalone_warning_is_clean() -> None:
    assert _axes(_READ_HOST_OK) == []


def test_incident_runbook_has_no_blocking_violation() -> None:
    """사고 당사자 런북은 정정됐다 — 유예 없이 차단 위반 0건이어야 한다(경고는 허용)."""
    count, found = sc.audit_file(_INCIDENT_RUNBOOK, sc.DbReach(_BACKEND))
    blocking = [v for v in found if v.axis != sc.WARNING_AXIS]
    assert count >= 8
    assert blocking == [], [f"{v.axis} {v.location}" for v in blocking]


# ═════════════════════════════════════════════════════════════════════════
# ① red 축 — acceptance ③의 뮤테이션 4종 + 절마다 반례
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("old", "new", "axis"),
    [
        # ③-1 사용 중인 세션 변수의 정의 제거 — `$Py`는 아래에서 실제로 쓰인다
        ('$Py = "$Repo\\src\\backend\\.venv\\Scripts\\python.exe"\n', "", "세션 변수"),
        # ③-2 cd 전부 제거
        ('cd "$Repo\\src\\backend"\n', "", "작업 폴더"),
        # ③-3 시스템 라벨 제거
        ("# [실행 시스템] Windows PowerShell (= Phaiakes9)\n", "", "라벨"),
        # ③-4 목적지 환경변수 주입 제거 — alembic·DB 도달 모듈이 실제로 뒤에 있다
        (
            '$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"\n',
            "",
            "DB 목적지",
        ),
        # 상대 경로 cd — 앞 블록이 남긴 위치에 기댄다
        ('cd "$Repo\\src\\backend"', "cd src\\backend", "작업 폴더"),
        # 라벨이 있어도 시스템을 말하지 않으면 라벨이 아니다("창 B"만)
        ("# [실행 시스템] Windows PowerShell (= Phaiakes9)", "# ── 창 B ──", "라벨"),
        # psql 목적지 — docker exec를 지우면 기본 호스트·포트로 떨어진다
        ("docker exec -i whymath-pg psql", "psql", "DB 목적지"),
    ],
)
def test_mutations_of_the_reference_block_turn_red(old: str, new: str, axis: str) -> None:
    mutated = _mutate(_REFERENCE.strip("\n") + "\n", old, new)
    assert axis in _axes(mutated), f"뮤테이션이 생존했다: {old!r} → {new!r}"


def test_cd_after_the_first_command_is_late() -> None:
    """cd가 있어도 첫 실행 명령 **뒤**면 그 명령은 앞 블록의 위치에서 돈다."""
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
git status --short
cd C:\Users\kiki\Desktop\__AI\WhyMath
"""
    assert "작업 폴더" in _axes(body)


def test_cd_to_an_undefined_variable_is_not_absolute() -> None:
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
cd $WT
git status --short
"""
    axes = _axes(body)
    assert "작업 폴더" in axes and "세션 변수" in axes


def test_cd_through_join_path_of_a_defined_variable_is_absolute() -> None:
    """괄호 식의 뿌리가 블록 안에서 정의된 변수면 절대다 — 2026-09-29 전수 실측 오탐 1건의 동결."""
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
$Wt = Join-Path $env:TEMP "whymath-wt"
cd (Join-Path $Wt "src\web\webapp")
npm.cmd ci
"""
    assert "작업 폴더" not in _axes(body)


def test_db_module_reached_before_the_injection_is_red() -> None:
    """목적지 대입이 **뒤에** 오면 그 앞의 DB 명령은 물려받은 값을 쓴다."""
    body = _mutate(
        _REFERENCE.strip("\n") + "\n",
        '$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"\n'
        "& $Py -m whymath_backend.ops.db_host_reachability\n",
        "& $Py -m whymath_backend.ops.db_host_reachability\n"
        '$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"\n',
    )
    assert "DB 목적지" in _axes(body)


def test_unknown_module_is_treated_as_a_db_command() -> None:
    """모듈을 찾지 못하면 DB 명령으로 본다 — 모른다 ≠ 아니다(이름이 바뀐 모듈일 수 있다)."""
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
python -m whymath_backend.no_such_module_for_eos_test
"""
    assert "DB 목적지" in _axes(body)


def test_integration_pytest_needs_a_destination() -> None:
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
$env:WHYMATH_RUN_INTEGRATION = "1"
python -m pytest -m integration
"""
    assert "DB 목적지" in _axes(body)


def test_read_host_without_standalone_warning_is_red() -> None:
    mutated = _mutate(
        _READ_HOST_OK.strip("\n") + "\n",
        "# ⚠ 이 블록만 단독으로 붙여넣는다 — 뒤 블록을 이어 붙이면 그 첫 줄이 입력값으로 삼켜진다.\n",
        "",
    )
    assert "Read-Host 단독" in _axes(mutated)


def test_standalone_warning_in_the_prose_before_the_fence_counts() -> None:
    """경고는 펜스 바로 앞 본문에 있어도 된다(`이 한 줄만 붙여넣는다` 표현 포함)."""
    mutated = _mutate(
        _READ_HOST_OK.strip("\n") + "\n",
        "# ⚠ 이 블록만 단독으로 붙여넣는다 — 뒤 블록을 이어 붙이면 그 첫 줄이 입력값으로 삼켜진다.\n",
        "",
    )
    assert "Read-Host 단독" not in _axes(mutated, ["### [A-3a] 동의 입력 — 이 한 줄만 붙여넣는다"])
    assert "Read-Host 단독" in _axes(mutated, ["이 블록은 입력을 기다린다"])


def test_read_host_in_a_write_guard_is_a_warning_not_a_block() -> None:
    """⑥ — 쓰기 가드가 Read-Host 결과에 기대면 **경고**다(차단 축은 단독 경고 문구)."""
    body = r"""
# [실행 시스템] Windows PowerShell (= Phaiakes9)
# ⚠ 이 블록만 단독으로 붙여넣는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Confirm = Read-Host "지우려면 DELETE"
$Ok = ($Confirm -ceq "DELETE")
if ($Ok) { docker exec -i whymath-pg psql -U whymath -d whymath -c "DELETE FROM t;"; "EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True OK=$Ok" }
"""
    assert _axes(body) == [sc.WARNING_AXIS]
    machine = _mutate(body, '$Ok = ($Confirm -ceq "DELETE")', '$Ok = (Test-Path "C:\\x")')
    assert sc.WARNING_AXIS not in _axes(machine), "오염되지 않은 가드까지 경고했다"


# ═════════════════════════════════════════════════════════════════════════
# ③ 판정기 경계 — 변수 스캐너
# ═════════════════════════════════════════════════════════════════════════
def _inherited(body: str) -> list[str]:
    return [name for _row, name in sc.scan_variables(_block(body)).inherited]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("'$Literal'", []),  # 작은따옴표 — 치환 없음
        ('"`$Escaped"', []),  # 백틱 이스케이프 — 치환 없음
        ('"$Interpolated"', ["interpolated"]),  # 큰따옴표 — 읽기
        ("$X = $X + 1", ["x"]),  # 우변이 먼저 평가된다 — 앞 블록의 값
        ("$Y = 1; $Z = $Y", []),  # 문장 경계 뒤에는 정의돼 있다
        ("$N += 1", ["n"]),  # 복합 대입은 읽기다
        ("$env:FOO_BAR", []),  # 환경변수는 DB 목적지 축의 영역
        ("$LASTEXITCODE; $true; $_", []),  # 자동 변수
        ("& $Py @Params", ["py", "params"]),  # 스플랫은 읽기다
        ("$A, $B = 1, 2\n$A + $B", []),  # 다중 대입
        ("$Files = @(1)\nforeach ($F in $Files) { $F }", []),  # foreach 변수
        ("$global:Shared", ["shared"]),  # 전역 범위도 세션 변수다
        ('$T = @"\n$Inside\n"@', ["inside"]),  # here-string 안의 치환
        ("# $InComment", []),  # 주석
        ("Get-Process -OutVariable Procs\n$Procs", []),  # -OutVariable 정의
    ],
)
def test_variable_scanner_semantics(body: str, expected: list[str]) -> None:
    assert _inherited(body) == expected


# ═════════════════════════════════════════════════════════════════════════
# ③ 판정기 경계 — DB 도달은 이름이 아니라 import 그래프
# ═════════════════════════════════════════════════════════════════════════
def test_db_reach_is_selective_and_follows_indirect_imports() -> None:
    reach = sc.DbReach(_BACKEND)
    # 적재 CLI는 자기 파일에 DB 표지가 없다 — 다른 모듈의 함수로 DB에 쓴다(간접 도달).
    assert reach.reaches_db("whymath_backend.l1.skill_graph.populate") is True
    assert reach.reaches_db("whymath_backend.ops.db_host_reachability") is True
    # 설정 정의처·라우터는 DB에 닿지 않는다 — 모든 모듈을 DB로 보면 판정이 공허해진다.
    assert reach.reaches_db("whymath_backend.config") is False
    assert reach.reaches_db("whymath_backend.l3.router") is False
    assert reach.reaches_db("whymath_backend.no_such_module_for_eos_test") is True


def test_db_reach_without_a_backend_treats_every_module_as_db() -> None:
    """백엔드 소스가 없으면 도달을 모른다 — 모른다 ≠ 아니다."""
    assert sc.DbReach(Path("/nonexistent-backend-root")).reaches_db("whymath_backend.config")


# ═════════════════════════════════════════════════════════════════════════
# ④⑤ 유예·측정 실패 (CLI 계약 — 종료 코드로 판정)
# ═════════════════════════════════════════════════════════════════════════
_VIOLATING = "## 블록\n\n```powershell\ncd src\\backend\ngit status --short\n```\n"


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCANNER),
            "--root",
            str(root),
            "--backend-root",
            str(_BACKEND),
            "--no-builtin-waivers",
            "--today",
            "2026-10-01",
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _repo_with(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "docs" / "ops" / "x_runbook.md"
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    return tmp_path


def test_violation_without_waiver_fails(tmp_path: Path) -> None:
    proc = _run(_repo_with(tmp_path, _VIOLATING))
    assert proc.returncode == 1, proc.stdout
    assert "라벨" in proc.stdout and "작업 폴더" in proc.stdout


def test_exact_waiver_passes(tmp_path: Path) -> None:
    proc = _run(_repo_with(tmp_path, _VIOLATING), "--waive", "docs/ops/x_runbook.md=2026-12-31=2")
    assert proc.returncode == 0, proc.stdout
    assert "[WAIVED]" in proc.stdout


@pytest.mark.parametrize(
    ("waiver", "marker"),
    [
        ("docs/ops/x_runbook.md=2026-12-31=3", "[유예 과대]"),  # 고친 만큼 줄이지 않았다
        ("docs/ops/x_runbook.md=2026-12-31=1", "[유예 초과]"),  # 새 위반이 섞였다
        ("docs/ops/x_runbook.md=2026-09-30=2", "[유예 만료]"),  # --today 2026-10-01
        ("docs/ops/gone_runbook.md=2026-12-31=1", "[유예 unmatched]"),
    ],
)
def test_waiver_mismatches_fail(tmp_path: Path, waiver: str, marker: str) -> None:
    proc = _run(_repo_with(tmp_path, _VIOLATING), "--waive", waiver)
    assert proc.returncode == 1, proc.stdout
    assert marker in proc.stdout


def test_no_markdown_is_a_measurement_failure(tmp_path: Path) -> None:
    proc = _run(tmp_path)
    assert proc.returncode == 1 and "측정 실패" in proc.stdout


def test_no_powershell_block_is_a_measurement_failure(tmp_path: Path) -> None:
    proc = _run(_repo_with(tmp_path, "# 문서\n\n```bash\nls\n```\n"))
    assert proc.returncode == 1 and "측정 실패" in proc.stdout


@pytest.mark.parametrize(
    "bad", ["docs/x.md=2026-12-31", "docs/x.md=bad=1", "docs/x.md=2026-12-31=0"]
)
def test_malformed_waiver_is_an_argument_error(tmp_path: Path, bad: str) -> None:
    proc = _run(_repo_with(tmp_path, _VIOLATING), "--waive", bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_builtin_waivers_expire_and_carry_counts() -> None:
    """만료 없는 유예 금지 — 전건이 만료일·건수를 갖고, 경로가 겹치지 않는다."""
    waivers = sc.SELF_CONTAINMENT_WAIVERS
    assert waivers, "유예 목록이 비었다면 이 테스트를 지우고 ④를 닫아라"
    assert len({w.path for w in waivers}) == len(waivers)
    for waiver in waivers:
        assert waiver.until <= date(2026, 12, 31), waiver
        assert waiver.count >= 1, waiver


def test_production_docs_pass_with_the_builtin_waivers() -> None:
    """저장소 전체가 게이트를 통과한다 — 새 위반·유예 불일치는 여기서도 RED다."""
    proc = subprocess.run(
        [sys.executable, str(_SCANNER), "--today", "2026-09-29"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout[-3000:]


# ═════════════════════════════════════════════════════════════════════════
# ⑤ 배선 실재 — 저장소에 있는 것과 도는 것은 다르다
# ═════════════════════════════════════════════════════════════════════════
def test_gate_is_wired_into_an_ungated_ci_job() -> None:
    """CI의 어느 잡이 이 게이트를 부르고, 그 잡이 docs만 바뀐 PR에서도 도는가."""
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    owners = [
        (name, job)
        for name, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if isinstance(step, dict)
        and "scripts/ops/check_runbook_self_containment.py" in step.get("run", "")
    ]
    assert owners, "CI 어느 잡도 check_runbook_self_containment.py를 부르지 않는다"
    for name, job in owners:
        assert (
            "needs" not in job and "if" not in job
        ), f"{name} 잡은 조건부다 — 런북은 docs만 바뀐 PR에서 바뀌므로 무조건 도는 잡에 둬라"
