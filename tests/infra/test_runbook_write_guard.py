"""런북 쓰기 블록 가드 게이트의 **양방향 변별력 + 배선 실재** 동결 (HARN-106 ③④).

막는 것은 넷이다.

① **무변별(red 축)** — 가드 없는 쓰기·위장 가드·침묵 가드·고정 문자열 출력·관측 불가
   입력·파서 함정을 주입해도 통과하는 것. 각 축마다 *그 축이 없으면 통과하는* 픽스처를 둔다.
② **무변별(green 축)** — 정상 런북이 red면 게이트가 아니라 개발 차단기다. 권장 형태(한 줄
   `if … { … } else { … }`)와 읽기 전용 블록이 통과해야 한다.
③ **유예의 침묵** — 만료된 유예·가리키는 자리가 사라진(unmatched) 유예가 조용히 통과하는 것.
④ **측정 실패의 위장** — 스캔 0건을 통과로 읽는 것.

**절마다 그 절을 밟는 픽스처를 둔다**(CLAUDE.md「픽스처가 그 절을 실제로 밟는가」). 특히
`_SINGLE_LINE_GUARD`는 **초판이 실제로 오탐한 형태**다 — 줄 단위 중괄호 깊이만 보면 한 줄
가드가 "깊이 0"으로 돌아와 가드가 없는 것처럼 보인다. 그 절이 없으면 정정된 SKB-03 런북이
red가 된다.

마지막으로 **프로덕션 런북 전체가 green**임을 동결한다 — 유예를 늘리려면 이 테스트를
의식적으로 고쳐야 한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_blocks.py"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_FIXED_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "skb03_atom_node_populate_runbook.md"


def _runbook(body: str) -> str:
    """최소 런북 골격 — 파일명이 `*runbook*.md`여야 기본 글롭에 잡힌다."""
    return f"## 실행 블록\n\n```powershell\n{body.strip()}\n```\n"


# ── red 픽스처 — 이 상태를 주입했는데 통과하면 게이트가 아니다 ────────────────
_UNGUARDED_WRITE = """
# [Windows PowerShell · Phaiakes9]
& $Py -m whymath_backend.l1.atom_graph.populate
"POPULATE_EXIT=$LASTEXITCODE"
"""

_FAKE_GUARD_NO_VARIABLE = """
# 가드는 있으나 조건이 변수를 참조하지 않는다 — 모든 입력에서 같은 가지로 간다.
if ($true) { & $Py -m whymath_backend.l1.atom_graph.populate; "EXIT=$LASTEXITCODE" } else { "건너뜀" }
"""

_SILENT_GUARD = """
# else 가지가 없다 — 침묵하며 건너뛴 블록은 보호가 아니라 위장이다.
if ($PathsOk) { & $Py -m whymath_backend.l1.atom_graph.populate; "EXIT=$LASTEXITCODE" }
"""

_FIXED_STRING_ONLY = """
# 성공·실패 양쪽에서 같은 문자열을 낸다 — 무엇이 지워졌는지 말하지 않는다.
if ($Ready) { [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", $null, "Machine") } else { "건너뜀 — Ready=False" }
"Machine 스코프 정리 완료"
"""

_UNOBSERVABLE_INPUT = """
# 입력이 별표조차 보이지 않는다 — 붙여넣기 실패가 빈 값으로 조용히 통과한다.
$Secure = Read-Host "키를 입력하세요" -AsSecureString
"입력 완료"
"""

_DANGLING_ELSE = """
$Ready = $true
if ($Ready) {
  & $Py -m whymath_backend.l1.atom_graph.populate
}
else {
  "건너뜀"
}
"""

_WRITE_OUTSIDE_AN_EXISTING_GUARD = """
# 가드가 *있긴 한데* 쓰기가 그 밖에 있다 — 이 블록의 위험은 정확히 여기다.
# 이 픽스처가 없으면 `is_guarded` 절을 통째로 지워도(=전부 가드 안으로 계상) 통과한다:
# 가드가 아예 없는 블록은 "조건이 변수를 참조하지 않는다" 축이 우연히 덮어 주기 때문이다
# (2026-09-17 실측 M1 생존).
$Ready = $true
if ($Ready) { "준비됨" } else { "미준비 — Ready=$Ready" }
& $Py -m whymath_backend.l1.atom_graph.populate
"POPULATE_EXIT=$LASTEXITCODE"
"""

_WRITE_IN_THE_ELSE_BRANCH = """
# 쓰기가 **거부 가지**에 있다 — 재검사에 실패했는데 쓰는 것이라 뒤집힌 가드다.
# 이 픽스처가 없으면 true 가지 영역을 블록 끝까지 늘려도(=else까지 가드로 계상) 통과한다
# (2026-09-17 실측 M2 생존).
$Ready = $false
if ($Ready) { "준비됨" } else { & $Py -m whymath_backend.l1.atom_graph.populate; "EXIT=$LASTEXITCODE" }
"""

_DANGLING_ELSE_WITHOUT_OTHER_DEFECTS = """
# 파서 함정만 있는 블록 — 쓰기도 없고 침묵 가드도 아니다.
# `_DANGLING_ELSE`(쓰기 있음)로는 이 축을 밟지 못한다: 그쪽은 같은 줄 `} else {`가 아니라
# "말하는 else가 없다" 축이 먼저 잡아 버려, 파서 검사를 지워도 여전히 red다
# (2026-09-17 실측 M9 생존).
$Ready = $true
if ($Ready) { "준비됨" } else { "미준비 — Ready=$Ready" }
if ($Other) {
  "값=$Other"
}
else {
  "다른 값"
}
"""

_SQL_MUTATION_UNGUARDED = """
docker exec -i whymath-pg psql -U whymath -d whymath -c "DELETE FROM attempt_event WHERE user_id='$U';"
"DELETED=$LASTEXITCODE"
"""

# HARN-214 — 2026-10-07 G-misc40 적재 블록이 이 스캐너에서 "쓰기 0개"였다. 아래 셋은 그때 비어
# 있던 인식 범위(문자열 속 psql · 저장소 적재 CLI · 적재 함수 직접 호출)를 밟는 픽스처다.
# 각 픽스처는 **그 절이 없으면 통과하는** 형태다 — 가드 없는 쓰기인데 쓰기로 안 보이기 때문이다.
_WRAPPED_PSQL_DELETE_UNGUARDED = """
# psql이 cmd /c 문자열 안에 감싸였다 — 마스킹 텍스트는 그 안을 가려 psql도 DELETE도 못 본다.
cmd /c "docker exec -i whymath-pg psql -U whymath -d whymath -c \\"DELETE FROM misconception_crosslink WHERE mis_id='M0599'\\""
"DELETE_EXIT=$LASTEXITCODE"
"""

_LOAD_CLI_UNGUARDED = """
# 저장소 적재 CLI(`promote --load`)는 DB를 쓴다 — 쓰기 어휘에 없어 가드 없이 통과했던 형태.
& $Py -m whymath_backend.l4.misconception.crosslink_review promote --queue $Queue --load
"LOAD_EXIT=$LASTEXITCODE"
"""

_LOAD_CROSSLINKS_CALL_UNGUARDED = """
# 적재 함수 직접 호출 — 같은 DB 쓰기를 파이썬 한 줄로 부르는 형태.
& $Py -c "from whymath_backend.l1.misconception.crosslink_loader import load_crosslinks; print(load_crosslinks(None, '$Corpus'))"
"LOAD_EXIT=$LASTEXITCODE"
"""

# 파서 축의 *깊이 0* 절 — 닫힌 if 바로 다음 줄이 `} else {`로 시작하고 그 `}`가 닫을 바깥 가지가
# 없다. 중첩 정상 형태를 풀어 주는 `depth_before == 0` 조건을 지우면 이것이 통과해 버린다.
_STRAY_BRACE_ELSE_AT_DEPTH_ZERO = """
$Ready = $true
if ($Ready) { "준비됨" }
} else { "미준비 — Ready=$Ready" }
"""

# ── green 픽스처 — 이것이 red면 개발 차단기다 ───────────────────────────────
_SINGLE_LINE_GUARD = """
# 권장 형태 — 한 줄 `if … { … } else { … }`. 초판이 이것을 오탐했다.
$PathsOk = $PathsMatchMain -eq $true
$FlagOk = $HasSkipFlag -eq $true
if ($PathsOk -and $FlagOk) { & $Py -m whymath_backend.l1.atom_graph.populate; "POPULATE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — PATHS_OK=$PathsOk FLAG_OK=$FlagOk" }
"""

_READ_ONLY_BLOCK = """
# 쓰기가 없다 — 가드·되읽기 축은 적용되지 않는다.
$Before = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM atom_node;"
"BEFORE_TOTAL=$Before"
"""

_PATH_VARIABLE_NOT_A_WRITE = """
# 문자열 안의 `populate`는 *경로*지 실행이 아니다 — 문자열을 벗기면 남지 않는다.
$PopulateSrc = "src/backend/whymath_backend/l1/atom_graph/populate.py"
$HasSkipFlag = ((Get-Content $PopulateSrc -Raw) -match "skip-atom-node")
"HAS_SKIP_FLAG=$HasSkipFlag"
"""

_DIRECTORY_SCAFFOLD = """
# 작업 폴더 생성은 멱등하고 되돌리기 쉽다 — 이 게이트의 대상이 아니다.
New-Item -ItemType Directory -Force -Path work\\eos02 | Out-Null
"WORKDIR_READY=" + (Test-Path work\\eos02)
"""

_SECURE_STRING_VERIFIED = """
# `-AsSecureString`을 쓰되 같은 블록에서 길이를 검증한다(값은 출력하지 않는다).
$Secure = Read-Host "키를 입력하세요" -AsSecureString
$Plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure))
"KEY_LENGTH=" + ("$Plain").Length
"""


# 대화형 TUI가 환경 설정과 한 블록에 있다 — 붙여넣기 버퍼의 잔여 줄이 판정 프롬프트의
# 입력으로 먹힌다(2026-09-22 라이브 실측 · MP-11). 이 축이 없으면 통과하는 형태다.
_INTERACTIVE_WITH_SETUP = """
$env:PYTHONPATH = "C:\\repo\\src\\backend"
$PyExe = "C:\\repo\\.venv\\Scripts\\python.exe"
$Data = "C:\\out"
& $PyExe -m whymath_backend.harness.review_session --queue "$Data\\q.jsonl" --reviewer-id kiki
"""

# 같은 명령이 **혼자** 있으면 정당하다 — 붙여넣기 단위가 한 줄이라 버퍼가 남지 않는다.
# 이 대조군이 없으면 「대화형 명령 자체를 금지」하는 과잉 수정이 통과한다.
_INTERACTIVE_ALONE = """
& $PyExe -m whymath_backend.harness.review_session --queue "$Data\\q.jsonl" --reviewer-id kiki
"""

# `Read-Host`는 **의도적으로 대화형 축 밖**이다 — 한 줄만 읽고 반환하므로 버퍼를 비우는 것이
# 아니라 *한 줄을 소비하고 멈추는* 장치이고, CLAUDE.md가 붙여넣기 정지 수단으로 권장한다.
# 초판이 이것을 축에 넣었다가 실제 런북 2건의 정상 정지 장치를 red로 만들었다(2026-09-22).
_READ_HOST_WITH_SETUP = """
$Repo = "C:\\repo"
cd $Repo
"CWD=" + (Get-Location).Path
$Confirm = Read-Host "계속하려면 GO 를 입력하십시오"
"CONFIRM=$Confirm"
"""


# 중첩 가드 — 안쪽 `} else { … }`가 한 줄로 끝나고 다음 줄이 바깥 가지를 닫는 `} else { … }`다.
# 이 형태는 Kiki 머신 PowerShell에서 정상 실행됐다(2026-10-07). 깊이를 안 보던 초판은 앞 줄이
# `}`로 끝난다는 이유만으로 이것을 위반으로 오탐했다 — 그 절이 없으면 이 픽스처가 red가 된다.
_NESTED_GUARD_CLOSING = """
$Ready = $true
if ($Ready) {
  & $Py -m whymath_backend.l1.atom_graph.populate
  $Rc = $LASTEXITCODE
  if ($Rc -eq 0) {
    "POPULATE_OK rc=$Rc"
  } else { "POPULATE_FAILED rc=$Rc" }
} else { "WRITE_REFUSED=True — Ready=$Ready" }
"""

# 같은 세 쓰기 형태를 *정당하게* 가드한 대조군 — 이것이 없으면 "새 어휘는 무조건 위반"이라는
# 과잉 수정이 통과한다.
_WRAPPED_PSQL_DELETE_GUARDED = """
$Ready = $true
if ($Ready) { cmd /c "docker exec -i whymath-pg psql -U whymath -d whymath -c \\"DELETE FROM misconception_crosslink WHERE mis_id='M0599'\\""; "DELETE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — Ready=$Ready" }
"""

_LOAD_CLI_GUARDED = """
$QueueOk = $true
if ($QueueOk) { & $Py -m whymath_backend.l4.misconception.crosslink_review promote --queue $Queue --load; "LOAD_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — QueueOk=$QueueOk" }
"""

# 주석 속 SQL·읽기 전용 psql은 쓰기가 아니다 — `_code_text`가 원문을 보게 된 대가로 생길 수 있는
# 오탐을 막는 대조군이다(주석 줄 제외 절을 지우면 이 픽스처가 red가 된다).
_COMMENTED_SQL_IS_NOT_A_WRITE = """
# 아래는 하지 마세요: psql -c "DELETE FROM misconception_crosslink"
$Before = cmd /c "docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c \\"SELECT count(*) FROM misconception_crosslink\\""
"BEFORE_TOTAL=$Before"
"""


def _scan(tmp_path: Path, name: str, body: str, *, extra: list[str] | None = None) -> int:
    """픽스처 런북 1개를 만들어 스캐너를 돌린다 — 판정은 exit code로만 한다."""
    path = tmp_path / f"{name}_runbook.md"
    path.write_text(_runbook(body), encoding="utf-8")
    # 주입이 실제로 적용됐는지 먼저 단언한다(CLAUDE.md「주입 자체의 실재」).
    assert path.read_text(encoding="utf-8").strip(), "픽스처가 비어 있다 — 주입이 적용되지 않았다"
    result = subprocess.run(
        [sys.executable, str(_SCANNER), str(path), "--root", str(tmp_path), *(extra or [])],
        capture_output=True,
        text=True,
    )
    return result.returncode


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("unguarded", _UNGUARDED_WRITE),
        ("fake_guard", _FAKE_GUARD_NO_VARIABLE),
        ("silent_guard", _SILENT_GUARD),
        ("fixed_string", _FIXED_STRING_ONLY),
        ("unobservable_input", _UNOBSERVABLE_INPUT),
        ("dangling_else", _DANGLING_ELSE),
        ("sql_mutation", _SQL_MUTATION_UNGUARDED),
        ("write_outside_guard", _WRITE_OUTSIDE_AN_EXISTING_GUARD),
        ("write_in_else", _WRITE_IN_THE_ELSE_BRANCH),
        ("dangling_else_only", _DANGLING_ELSE_WITHOUT_OTHER_DEFECTS),
        ("interactive_with_setup", _INTERACTIVE_WITH_SETUP),
        ("wrapped_psql_delete", _WRAPPED_PSQL_DELETE_UNGUARDED),
        ("load_cli", _LOAD_CLI_UNGUARDED),
        ("load_crosslinks_call", _LOAD_CROSSLINKS_CALL_UNGUARDED),
        ("stray_brace_else_depth_zero", _STRAY_BRACE_ELSE_AT_DEPTH_ZERO),
    ],
)
def test_each_defect_is_caught(tmp_path: Path, name: str, body: str) -> None:
    """red 축 — 주입한 결함마다 exit 1이 나야 한다(하나라도 통과하면 그 축은 무방비다)."""
    assert _scan(tmp_path, name, body) == 1


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("single_line_guard", _SINGLE_LINE_GUARD),
        ("read_only", _READ_ONLY_BLOCK),
        ("path_variable", _PATH_VARIABLE_NOT_A_WRITE),
        ("directory_scaffold", _DIRECTORY_SCAFFOLD),
        ("secure_verified", _SECURE_STRING_VERIFIED),
        ("interactive_alone", _INTERACTIVE_ALONE),
        ("read_host_with_setup", _READ_HOST_WITH_SETUP),
        ("nested_guard_closing", _NESTED_GUARD_CLOSING),
        ("wrapped_psql_guarded", _WRAPPED_PSQL_DELETE_GUARDED),
        ("load_cli_guarded", _LOAD_CLI_GUARDED),
        ("commented_sql", _COMMENTED_SQL_IS_NOT_A_WRITE),
    ],
)
def test_legitimate_forms_pass(tmp_path: Path, name: str, body: str) -> None:
    """green 축 — 정당한 형태가 red면 게이트가 아니라 개발 차단기다."""
    assert _scan(tmp_path, name, body) == 0


def test_waiver_suppresses_but_expiry_restores(tmp_path: Path) -> None:
    """유예는 막되 **만료되면 다시 위반**이다 — 만료 없는 그랜드파더는 금지다."""
    rel = "unguarded_runbook.md"
    assert _scan(tmp_path, "unguarded", _UNGUARDED_WRITE) == 1
    live = _scan(
        tmp_path,
        "unguarded",
        _UNGUARDED_WRITE,
        extra=[f"--waive={rel}=2026-12-31", "--today=2026-09-17"],
    )
    assert live == 0, "유효한 유예가 막지 못했다"
    expired = _scan(
        tmp_path,
        "unguarded",
        _UNGUARDED_WRITE,
        extra=[f"--waive={rel}=2026-09-16", "--today=2026-09-17"],
    )
    assert expired == 1, "만료된 유예가 조용히 통과했다"


def test_unmatched_waiver_fails(tmp_path: Path) -> None:
    """위반이 아닌데 유예가 남아 있으면 exit 1 — 목록이 거짓이 되는 것을 막는다.

    이 규칙이 실제로 일을 했다: 초판이 `ip_separation_evidence_gate_runbook.md`를 유예에
    넣었는데 그 런북은 원래 위반이 아니었고, 이 검사가 그것을 지우게 했다.
    """
    rel = "read_only_runbook.md"
    assert (
        _scan(
            tmp_path,
            "read_only",
            _READ_ONLY_BLOCK,
            extra=[f"--waive={rel}=2026-12-31", "--today=2026-09-17"],
        )
        == 1
    )


def test_zero_scan_is_failure(tmp_path: Path) -> None:
    """대상을 하나도 못 찾으면 실패다 — 공허하게 통과하는 전수 가드를 만들지 않는다."""
    result = subprocess.run(
        [sys.executable, str(_SCANNER), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "측정 실패" in result.stdout


def test_bad_waiver_syntax_exits_2(tmp_path: Path) -> None:
    """인자 오류(2)와 위반(1)을 구분한다 — 섞으면 실패 원인이 사라진다."""
    assert _scan(tmp_path, "read_only", _READ_ONLY_BLOCK, extra=["--waive=만료일없음"]) == 2


def test_production_runbooks_are_green() -> None:
    """프로덕션 트리 자체가 green임을 동결한다 — 유예를 늘리려면 여기를 의식적으로 고쳐야 한다."""
    result = subprocess.run(
        [sys.executable, str(_SCANNER)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "런북 " in result.stdout


def test_the_incident_runbook_carries_a_self_refusing_guard() -> None:
    """사고 당사자 런북(SKB-03)이 실제로 정정됐는가 — 게이트 통과와 별개로 *내용*을 본다.

    게이트만 믿으면 "유예로 덮었는데 통과"와 "정말 고쳤다"를 구분할 수 없다.
    """
    text = _FIXED_RUNBOOK.read_text(encoding="utf-8")
    assert "WRITE_REFUSED=True" in text, "자가거부 가드의 거부 출력이 없다"
    assert "} else {" in text, "같은 줄의 `} else {` 형태가 아니다(파서 함정)"
    # 가드가 참조하는 판정 변수를 앞 블록이 **실제로 만들어야** 한다(장식 가드 금지).
    assert "$PathsMatchMain = " in text
    assert "$HasSkipFlag = " in text


def test_scanner_is_wired_into_ci() -> None:
    """저장소에 있는 것과 도는 것은 다르다 — CI 잡이 이 스캐너를 실제로 부르는가.

    이 저장소는 같은 형태로 반복해서 뚫렸다(OPS-03 `tests/infra` 미실행 · OPS-08 required
    check 미강제 · OPS-11 lint 미배선). 배선 실재성은 기계가 동결한다.
    """
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    commands = [
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    assert any("check_runbook_blocks" in command for command in commands), (
        "CI 어느 잡도 check_runbook_blocks.py를 부르지 않는다 — "
        "'저장소에 존재함'은 '돌아감'이 아니다."
    )


# ── HARN-214 알려진 한계 고정 ────────────────────────────────────────────────
def _write_hit_count(tmp_path: Path, body: str) -> int:
    """스캐너 모듈을 직접 불러 한 블록의 쓰기 인식 건수를 센다(서브프로세스 판정과 별개)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_check_runbook_blocks_under_test", _SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    path = tmp_path / "probe_runbook.md"
    path.write_text(_runbook(body), encoding="utf-8")
    blocks = module.parse_runbook(path)
    assert len(blocks) == 1, "탐침 런북은 블록이 정확히 1개여야 한다"
    return len(module.write_hits(blocks[0]))


@pytest.mark.parametrize(
    ("name", "body"),
    [
        # 사고 블록의 실제 형태 — 변수 경유 적재 스크립트 + 파일 입력 SQL.
        ("variable_hidden_script", "& $PyExe $LoadPy $Corpus"),
        (
            "sql_in_variable",
            '$q = "DELETE FROM t"\ndocker exec -i whymath-pg psql -U whymath -d whymath -c $q',
        ),
        (
            "sql_from_file",
            'cmd /c "docker exec -i whymath-pg psql -U whymath -d whymath -At -f - < $SqlDel"',
        ),
    ],
)
def test_known_blind_spots_stay_pinned(tmp_path: Path, name: str, body: str) -> None:
    """텍스트 스캔으로 **볼 수 없는** 쓰기는 현재 판정(0건)을 고정한다 — 사고 블록이 이 형태다.

    이 테스트가 깨졌다면 누군가 인식 범위를 넓힌 것이다. 그것은 좋은 일일 수 있으나 같은 변경이
    정상 패턴(상태를 읽고 → 가드로 판정하고 → 쓴다)의 **가드 앞 읽기**를 위반으로 만들지 않는지
    먼저 확인하고(HARN-214 시험에서 파일 입력 SQL을 쓰기로 취급했더니 그렇게 됐다) 스캐너
    docstring의 「알려진 한계」 절을 함께 고쳐라.
    """
    assert (
        _write_hit_count(tmp_path, body) == 0
    ), f"{name}: 인식 범위가 바뀌었다 — docstring 한계 절 갱신"


def test_scanner_documents_its_blind_spots() -> None:
    """한계가 코드에만 있고 안내문에 없으면 사람은 "스캐너 통과 = 안전"으로 읽는다."""
    text = _SCANNER.read_text(encoding="utf-8")
    assert "알려진 한계" in text
    for marker in ("변수 경유 실행", "변수에 담은 SQL", "파일·표준입력 SQL", "변경 범위의 의미"):
        assert marker in text, f"한계 절에 `{marker}`가 없다"
