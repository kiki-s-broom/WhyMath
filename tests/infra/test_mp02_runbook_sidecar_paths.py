"""MP-02 런북의 사이드카 경로가 **실제 코드가 만드는 이름과 같은지** 동결 (MP-06 ③).

막는 것 — 문서↔코드 표류
------------------------
런북 §3·§4·§5는 회차 산출물의 사이드카(`*.rounds.jsonl`·`*.genlog.jsonl`·`*.review.jsonl`)
경로를 스스로 계산한다. 초판은 그것을 `<out>` + `".rounds.jsonl"` **이어붙이기**로 짰으나,
실제 코드는 `Path.with_suffix()`로 마지막 확장자를 **교체**한다. 두 공식은 서로 다른 파일을
가리키므로(`problems.jsonl.rounds.jsonl` vs `problems.rounds.jsonl`) §3의 재실행 차단이 실제
사이드카를 한 번도 찾지 못했고, **같은 회차가 2번 기록됐다**(2026-09-10 Kiki 실행 로그 ·
둘 다 accepted=0이라 코퍼스 오염은 없었다).

왜 "금지 문자열 열거"가 아니라 **산출 이름 대조**인가
---------------------------------------------------
"이 문자열을 쓰지 마라" 형태는 표기 변형에서 뚫린다(CLAUDE.md「금지 패턴 열거 대신 산출물
검사」). 그래서 이 테스트는 양쪽에서 *만들어지는 파일 이름*을 계산해 대조한다 — 런북 쪽은
코드 블록의 표현에서, 코드 쪽은 기본 경로 헬퍼 3종의 AST에서 뽑는다. 공식이 바뀌든 헬퍼가
바뀌든 **결과 이름이 갈리는 순간** RED다(양방향 표류 차단).

왜 import가 아니라 AST인가
--------------------------
이 테스트가 사는 CI 잡 `infra-contracts`는 **백엔드를 설치하지 않는다**(의존 7종 명시).
그리고 이 잡을 고른 이유는 `needs: changes` 게이팅이 없어 **docs만 바뀐 PR에서도 반드시
돌기** 때문이다 — 런북은 정확히 그런 PR에서 바뀌므로 backend 잡에 두면 통째로 놓친다.

스캔 0건은 실패
--------------
표현을 하나도 못 찾은 전수 가드는 공허하게 통과한다(CLAUDE.md). 그래서 사이드카 3종이
**전부** 런북 코드 블록에 실재하는 것까지 단언한다 — 절이 사라지면 RED다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "docs" / "reviews" / "mp02_first_llm_authoring_run_runbook.md"
_HARNESS = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "harness"

# 코드 쪽 정본 — 사이드카 기본 경로를 만드는 헬퍼 3종.
_HELPERS: tuple[tuple[str, Path], ...] = (
    ("default_round_ledger_path", _HARNESS / "anchor_round_ledger.py"),
    ("default_generation_log_path", _HARNESS / "problem_corpus_accumulate.py"),
    ("default_review_queue_path", _HARNESS / "problem_corpus_accumulate.py"),
)

# 런북 §3이 실제로 쓰는 산출 경로 — 이름 계산에만 쓰이며 파일을 만들지 않는다.
_OUT = Path("data/corpus/problem_bank_mp02_first_run_v0/problems.jsonl")

# 사이드카 이름을 만드는 두 *형태*. 각 형태가 내는 결과 이름을 계산해 코드와 대조한다.
_WITH_SUFFIX = re.compile(r"with_suffix\(\s*['\"](\.(?:rounds|genlog|review)\.jsonl)['\"]\s*\)")
_CONCAT = re.compile(
    r"""(?:\$Out|str\(out\)\s*\+\s*|['"]\s*\+\s*)['"]?(\.(?:rounds|genlog|review)\.jsonl)"""
)


def _helper_suffix(func_name: str, source: Path) -> str:
    """헬퍼가 `with_suffix()`에 넘기는 확장자 리터럴을 AST로 뽑는다."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != func_name:
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "with_suffix"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            ):
                return call.args[0].value
        raise AssertionError(
            f"{func_name}이 `with_suffix(<리터럴>)`로 사이드카 경로를 만들지 않는다 "
            f"({source}). 코드 공식이 바뀌었다면 런북 §3·§4·§5도 함께 고쳐야 한다."
        )
    raise AssertionError(f"헬퍼 {func_name}을 {source}에서 찾지 못했다")


def _expected_names() -> set[str]:
    return {_OUT.with_suffix(_helper_suffix(name, src)).name for name, src in _HELPERS}


def _fenced_blocks(text: str) -> list[str]:
    """코드 펜스 안만 본다 — 산문(정정 블록)은 *틀린 공식을 설명하려고* 인용하므로 제외한다."""
    return re.findall(r"^```[a-zA-Z]*\n(.*?)^```", text, re.S | re.M)


def _produced_names(line: str) -> list[str]:
    """이 줄의 사이드카 표현이 만들어 내는 **파일 이름**들."""
    names = [_OUT.with_suffix(suffix).name for suffix in _WITH_SUFFIX.findall(line)]
    names += [_OUT.name + suffix for suffix in _CONCAT.findall(line)]
    return names


def _runbook_names() -> list[str]:
    names: list[str] = []
    for block in _fenced_blocks(_RUNBOOK.read_text(encoding="utf-8")):
        for line in block.splitlines():
            names.extend(_produced_names(line))
    return names


def test_runbook_sidecar_names_match_code() -> None:
    """런북이 계산하는 이름이 전부 코드가 만드는 이름이어야 한다."""
    expected = _expected_names()
    produced = _runbook_names()
    assert produced, "런북 코드 블록에서 사이드카 표현 0건 — 스캔 0건은 통과가 아니라 실패다"
    drifted = sorted({n for n in produced if n not in expected})
    assert not drifted, f"런북↔코드 사이드카 이름 표류: {drifted} (코드 기대값 {sorted(expected)})"


def test_runbook_covers_all_three_sidecars() -> None:
    """3종이 전부 실재해야 한다 — 절이 사라지면 위 테스트가 공허하게 통과한다."""
    assert set(_runbook_names()) == _expected_names()


@pytest.mark.parametrize(
    "line",
    [
        '$Stale = @($Out, "$Out.rounds.jsonl", "$Out.genlog.jsonl", "$Out.review.jsonl")',
        "led=rows(str(out)+'.rounds.jsonl')",
        '$RunId = (Get-Content "$Out.rounds.jsonl" | Select-Object -Last 1)',
    ],
)
def test_detector_flags_the_original_bug(line: str) -> None:
    """변별력 증명 — 사고를 일으킨 *이어붙이기* 형태는 코드와 다른 이름을 내야 한다.

    이 픽스처가 없으면 위 두 테스트는 "모든 입력에서 초록"인 가드와 구별되지 않는다
    (CLAUDE.md「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」).
    """
    produced = _produced_names(line)
    assert produced, f"이어붙이기 형태를 탐지하지 못했다: {line}"
    assert all(name not in _expected_names() for name in produced)
    assert all(name.startswith("problems.jsonl.") for name in produced)


# ── MP-08 — 인코딩 축 ────────────────────────────────────────────────────────
# 2026-09-21 라이브 회차에서 결함 2건이 났다. 둘 다 *런북*의 결함이고, 둘 다 한국어 Windows
# 에서만 발현한다 — CI(리눅스·UTF-8)는 구조적으로 재현할 수 없는 구간이라 여기서 **문면을**
# 동결한다(실행이 아니라 형태를 본다는 뜻이다).
#
#   ⓐ `Get-Content`가 UTF-8 JSONL을 로케일 인코딩(cp949)으로 읽어 `ConvertFrom-Json`이 실패
#      → run_id 추출 실패 → 리콜 리허설 공전. 파일은 온전했고 읽기측만 깨졌다.
#   ⓑ 회차 리포트가 stdout에서 UnicodeEncodeError(cp949·U+2014)로 잘려 `ACCUMULATE_EXIT=1`이
#      *카나리 차단*인지 *크래시*인지 구분 불가가 됐다.
#
# ⓐ는 **형태의 부재**로, ⓑ는 **설정의 실재**로 동결한다. 방향이 다른 이유: PowerShell JSON
# 파싱은 이 런북에 있어야 할 이유가 없으므로 0건이 정답이고(`-Encoding UTF8`을 덧붙이는 부분
# 정정은 블록마다 재발한다), 출력 인코딩은 설정이 *있어야* 보험이 되기 때문이다.

_PS_JSON_PARSE = "ConvertFrom-Json"
_IO_ENCODING = "PYTHONIOENCODING"


def _fenced_text() -> str:
    return "\n".join(_fenced_blocks(_RUNBOOK.read_text(encoding="utf-8")))


def test_runbook_has_no_powershell_json_parsing() -> None:
    """런북 코드 블록에 PowerShell JSON 파싱이 0건이어야 한다(ⓐ).

    산문(정정 블록)은 *그 함정을 설명하려고* 이름을 인용하므로 펜스 안만 본다.
    """
    assert _PS_JSON_PARSE not in _fenced_text(), (
        f"런북 실행 블록에 {_PS_JSON_PARSE}가 있다 — PowerShell은 파일을 로케일 인코딩"
        "(한국어 Windows=cp949)으로 읽어 한글 JSON에서 깨진다. Python 경유로 바꿔야 한다."
    )


def test_runbook_forces_utf8_stdout() -> None:
    """런북이 stdout UTF-8 보험을 설정하고 **그것을 자가검증**해야 한다(ⓑ).

    설정만으로는 부족하다 — 설정이 먹은 창과 안 먹은 창이 같은 화면을 내면 그 단계는 검증이
    아니라 위장이다(2026-07-17 「변별력 없는 검증 스텝 금지」).
    """
    fenced = _fenced_text()
    assert (
        _IO_ENCODING in fenced
    ), f"런북 실행 블록에 {_IO_ENCODING} 설정이 없다 — 회차 리포트가 cp949에서 잘린다"
    assert (
        "IO_ENCODING" in fenced
    ), "설정만 있고 자가검증 출력이 없다 — 설정이 먹었는지 사람이 확인할 수 없다"
