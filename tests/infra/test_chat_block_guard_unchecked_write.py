"""HARN-300 — 채팅 실행 블록: 쓰기 단계 뒤 확인 없는 파괴 단계 · 한글 here-string 파이프의 변별력 동결.

**왜 이 규칙이 있는가**: 2026-10-07 G-misc40 라이브 DB 동기화 블록에서 로더 적재가 외래키 위반으로
실패했는데 블록이 종료 코드를 확인하지 않고 다음 단계의 DELETE 2건을 실행했다(DB가 일시적으로
의도보다 나쁜 상태가 됐다). 같은 날 같은 블록의 한글 판정 스크립트는 `$Pre | python -`로 넘겨지다
Windows PowerShell 5.1의 `$OutputEncoding`(기본 ASCII)이 한글을 `?`로 바꿔 판정이 거짓이 됐다.
선례 계열 = check-result-not-gating(2026-09-29) · encoding-cp949.

**이 파일이 지키는 것**:
  ① 실제 사고 블록(`INCIDENT_SYNC`)이 종료코드 축에서 RED — 정본 재현.
  ② 정상 형태(적재 직후 종료 코드를 받아 그 변수로 파괴를 감싼 블록)는 GREEN.
  ③ 대조군 — 파괴 단계만 있는 블록·읽기 전용 블록·파괴가 적재보다 앞서는 블록은 GREEN
     (전부 위반으로 접는 과잉 수정 방지).
  ④ 위장 — 종료 코드를 변수에 받기만 하고 파괴를 그 변수로 감싸지 않은 블록은 RED.
  ⑤ 인코딩 — 한글 here-string을 네이티브 프로세스에 파이프하면 RED, 같은 스크립트를 `chr()`
     숫자로 쓰거나 파이프하지 않으면 GREEN.
  ⑥ 훅 실행 경로 — 실제 Stop 훅이 사고 블록을 막는다(exit 2·로그 축 `종료코드`).

**한계(명시)**: 쓰기·파괴 어휘는 정규식 목록이라 목록 밖의 도구(예: 임의 CLI의 `--purge`)는
못 본다. 파괴가 변수 경유(`$Sql = "delete …"; psql -c $Sql`)이면 문장 속 문자열이 아니라 보지
못한다. 적재 대상의 외래키 존재 확인(HARN-300 ②)은 이 규칙이 하지 않는다 — 적재 계획 대비
건수 단언(HARN-215)과 함께 판단한다.

hermetic: 순수 함수 + 임시 파일만 — 네트워크·DB 0.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _REPO_ROOT / ".claude" / "hooks" / "chat_block_guard.py"
_SCANNER = _REPO_ROOT / "scripts" / "ops" / "check_runbook_blocks.py"

F = "```"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load("check_runbook_blocks_for_300", _SCANNER)
guard = _load("chat_block_guard_for_300", _GUARD)


def _ps(body: str) -> str:
    return f"다음을 실행하세요.\n{F}powershell\n{body.strip()}\n{F}\n끝."


def _axes(text: str) -> list[str]:
    return [f.axis for f in guard.audit_reply(scanner, text)]


# 2026-10-07 사고 블록의 형태 재구성 — 한 줄 가드 안에서 적재 뒤 DELETE가 종료 코드 확인 없이 이어졌다.
INCIDENT_SYNC = _ps(r"""
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Go = $CorpusOk -and $CodeOk -and $DbOk
if ($Go) { "BEFORE:"; docker exec whymath-pg psql -U whymath -d whymath -c "select 1;"; $env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://x"; $Load | python -; docker exec whymath-pg psql -U whymath -d whymath -c "delete from misconception_crosslink where mis_id = 'M0599'; delete from misconception_crosslink where mis_id = 'M0672' and confidence is null;"; "AFTER:" } else { "WRITE_REFUSED=True" }
""")

# 수정본 — 적재 직후 종료 코드를 받아 파괴를 그 변수로 감싼다.
FIXED_SYNC = _ps(r"""
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Load | python -
$LoadRc = $LASTEXITCODE
"LOAD_EXIT=$LoadRc"
if ($LoadRc -eq 0) { docker exec whymath-pg psql -U whymath -d whymath -c "delete from misconception_crosslink where mis_id = 'M0599';" } else { "REFUSED — LOAD_EXIT=$LoadRc" }
""")

# 같은 수정을 한 줄 `$LASTEXITCODE` 직접 조건으로 쓴 형태.
FIXED_DIRECT = _ps(r"""
$Load | python -
if ($LASTEXITCODE -eq 0) { docker exec whymath-pg psql -U whymath -d whymath -c "delete from t where id = 1;" } else { "REFUSED" }
""")

# 위장 — 종료 코드를 변수에 받고 출력만 하며, DELETE는 그 변수와 무관하게 실행된다.
FAKE_CHECK = _ps(r"""
$Load | python -
$LoadRc = $LASTEXITCODE
"LOAD_EXIT=$LoadRc"
docker exec whymath-pg psql -U whymath -d whymath -c "delete from misconception_crosslink where mis_id = 'M0599';"
""")

# 대조군 — 읽기 전용 · 파괴만 · 순서 반대.
READ_ONLY = _ps(r"""
docker exec whymath-pg psql -U whymath -d whymath -c "select count(*) from misconception_crosslink;"
""")
DESTRUCTIVE_ONLY = _ps(r"""
docker exec whymath-pg psql -U whymath -d whymath -c "delete from misconception_crosslink where mis_id = 'M0599';"
""")
DESTRUCTIVE_BEFORE_WRITE = _ps(r"""
docker exec whymath-pg psql -U whymath -d whymath -c "delete from misconception_crosslink where mis_id = 'M0599';"
$Load | python -
""")
# 한 psql 문자열 안의 INSERT+DELETE — 한 트랜잭션이라 문장 사이 순서 문제가 없다.
SINGLE_STATEMENT_TX = _ps(r"""
docker exec whymath-pg psql -U whymath -d whymath -c "begin; insert into t values (1); delete from t where id = 2; commit;"
""")
# here-string 본문에 쓰기·파괴 어휘가 있어도 명령이 아니다.
HERESTRING_WORDS = _ps(r"""
$Doc = @'
먼저 python -m loader --load 로 적재한다.
그 다음에 delete from t 같은 파괴 단계는 이 문서에서 실행하지 않는다.
'@
"DOC_READY"
""")


# ===========================================================================
# ① 정본 재현 · ② 정상 GREEN · ④ 위장 RED
# ===========================================================================


def test_red_incident_sync_block() -> None:
    assert "종료코드" in _axes(INCIDENT_SYNC)


@pytest.mark.parametrize("text", [FIXED_SYNC, FIXED_DIRECT])
def test_green_exit_code_gated_destructive(text: str) -> None:
    assert "종료코드" not in _axes(text)


def test_red_exit_code_captured_but_not_gating() -> None:
    assert "종료코드" in _axes(FAKE_CHECK)


# ===========================================================================
# 어휘 전수 — 쓰기·파괴 어휘 **항목마다** 그 항목이 없으면 통과하는 반례를 둔다.
# (뮤테이션에서 `--load` 항을 지워도 통과해, 어떤 픽스처도 그 절을 밟지 않는다는 것이 드러났다.)
# ===========================================================================

WRITE_FORMS = {
    "--load": "python -m whymath_backend.l4.misconception.crosslink_review promote --queue q.json --load",
    "load_ 함수": 'python -c "from m import load_rows; load_rows(1)"',
    "insert into": 'docker exec db psql -U u -d d -c "insert into t values (1);"',
    "update set": 'docker exec db psql -U u -d d -c "update t set a = 1;"',
    "upsert": "python tools/run.py --mode upsert",
    "on conflict": 'docker exec db psql -U u -d d -c "insert x on conflict do nothing;"',
    "변수 경유 파이프": "$Load | python -",
}
DESTRUCTIVE_FORMS = {
    "delete from": 'docker exec db psql -U u -d d -c "delete from t where id = 1;"',
    "drop table": 'docker exec db psql -U u -d d -c "drop table t;"',
    "truncate": 'docker exec db psql -U u -d d -c "truncate t;"',
    "Remove-Item": "Remove-Item C:\\tmp\\x -Recurse",
    "rm -rf": "rm -rf /tmp/x",
    "git reset --hard": "git reset --hard origin/main",
    "git clean -fd": "git clean -fd",
    "git push --force": "git push origin main --force",
}
SAFE_WRITE = "$Load | python -"
SAFE_DESTRUCTIVE = 'docker exec db psql -U u -d d -c "delete from t where id = 1;"'


@pytest.mark.parametrize("name", list(WRITE_FORMS))
def test_red_every_write_form_is_recognised(name: str) -> None:
    text = _ps(f"{WRITE_FORMS[name]}\n{SAFE_DESTRUCTIVE}")
    assert "종료코드" in _axes(text), name


@pytest.mark.parametrize("name", list(DESTRUCTIVE_FORMS))
def test_red_every_destructive_form_is_recognised(name: str) -> None:
    text = _ps(f"{SAFE_WRITE}\n{DESTRUCTIVE_FORMS[name]}")
    assert "종료코드" in _axes(text), name


@pytest.mark.parametrize("name", list(DESTRUCTIVE_FORMS))
def test_green_every_destructive_form_when_gated(name: str) -> None:
    """대조군 — 같은 파괴 어휘라도 종료 코드 변수로 감싸면 통과한다(전부 RED로 접는 과잉 수정 방지)."""
    body = f'{SAFE_WRITE}\n$Rc = $LASTEXITCODE\nif ($Rc -eq 0) {{ {DESTRUCTIVE_FORMS[name]} }} else {{ "REFUSED" }}'
    assert "종료코드" not in _axes(_ps(body)), name


# ===========================================================================
# ③ 대조군 — 과잉 수정 방지
# ===========================================================================


@pytest.mark.parametrize(
    "text",
    [READ_ONLY, DESTRUCTIVE_ONLY, DESTRUCTIVE_BEFORE_WRITE, SINGLE_STATEMENT_TX, HERESTRING_WORDS],
    ids=["read-only", "destructive-only", "delete-before-load", "single-tx", "herestring-words"],
)
def test_green_controls(text: str) -> None:
    assert "종료코드" not in _axes(text)


def test_split_statements_keeps_semicolons_inside_quotes() -> None:
    line = 'docker exec x -c "delete a; delete b;"; $Rc = $LASTEXITCODE'
    assert [s.strip() for _c, s in guard._split_statements(line)] == [
        'docker exec x -c "delete a; delete b;"',
        "$Rc = $LASTEXITCODE",
    ]


# ===========================================================================
# ⑤ 인코딩 — 한글 here-string 파이프
# ===========================================================================

KOREAN_PIPED = _ps(r"""
$Pre = @'
D = "직접매핑"
print(D)
'@
$Pre | python -
""")
ASCII_PIPED = _ps(r"""
$Pre = @'
D = "".join(chr(c) for c in (0xC9C1, 0xC811, 0xB9E4, 0xD551))
print(D)
'@
$Pre | python -
""")
KOREAN_NOT_PIPED = _ps(r"""
$Memo = @'
직접매핑은 관계 강도다.
'@
$Memo
""")
KOREAN_DISPLAY_STRING = _ps(r"""
"PRECHECK 코퍼스판정=$CorpusOk"
python -c "print(1)"
""")


def test_encoding_fixtures_are_what_they_claim_to_be() -> None:
    """픽스처 자체의 실재 — 대조군은 **정말 ASCII**이고 위반 픽스처는 **정말 한글을 담는다**.

    2026-10-07 사고: 같은 날 세션이 가설 검증용 파일에 쓴 `\\uXXXX` 이스케이프가 파일에 기록되기 전에
    한글로 풀려, "한글을 `?`로 바꾼 변형" 실험이 가설을 검증하지 못했다(대조군이 ASCII가 아니었다).
    픽스처가 의도한 성질을 갖는다는 것을 값으로 못 박아 같은 무효 검증을 막는다.
    """
    ascii_body = ASCII_PIPED.split(F + "powershell", 1)[1].split(F, 1)[0]
    assert all(ord(ch) < 128 for ch in ascii_body), "대조군 픽스처에 비ASCII 문자가 섞였다"
    korean_body = KOREAN_PIPED.split(F + "powershell", 1)[1].split(F, 1)[0]
    assert any(ord(ch) > 127 for ch in korean_body), "위반 픽스처에 한글이 없다"


def test_red_korean_herestring_piped_to_python() -> None:
    assert "인코딩" in _axes(KOREAN_PIPED)


@pytest.mark.parametrize(
    "text",
    [ASCII_PIPED, KOREAN_NOT_PIPED, KOREAN_DISPLAY_STRING],
    ids=["ascii-piped", "korean-not-piped", "korean-display-string"],
)
def test_green_encoding_controls(text: str) -> None:
    assert "인코딩" not in _axes(text)


# ===========================================================================
# ⑥ 훅 실행 경로 — 실제 Stop 훅
# ===========================================================================


def _run_hook(tmp_path: Path, reply: str) -> subprocess.CompletedProcess[str]:
    transcript = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": "해줘"}},
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {"content": [{"type": "text", "text": reply}]},
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    payload = {"transcript_path": str(transcript), "session_id": "t", "stop_hook_active": False}
    return subprocess.run(
        [sys.executable, str(_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=False,
    )


def test_hook_blocks_the_incident_sync_block(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, INCIDENT_SYNC)
    assert result.returncode == 2
    log = tmp_path / ".claude" / "logs" / "chat_block_violations.jsonl"
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert "종료코드" in row["axes"]


def test_hook_passes_the_fixed_block(tmp_path: Path) -> None:
    assert _run_hook(tmp_path, FIXED_SYNC).returncode == 0
