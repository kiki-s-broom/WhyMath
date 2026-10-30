"""P3-42 런북의 사이드카 프로브(`docs/ops/p3_42_probe.py`)와 런북이 서로 어긋나지 않게 동결한다.

막는 것 — 런북이 기대하는 SHA-256 과 실제 사이드카가 갈리는 표류
------------------------------------------------------------------
런북 블록 [C]는 프로브를 git 에서 받아 `$ProbeSha` 와 대조하고, [D]·[E]는 그 일치를 가드 조건으로
삼는다. 프로브를 고치고 런북의 해시를 안 고치면 Kiki 머신에서 `PROBE_SHA256_OK=False` 로 실행이
막힌다(안전하지만 왕복 1회). 이 테스트는 그 표류를 CI 에서 먼저 잡는다. 2026-10-16 실행에서 111줄
Python 을 붙여넣게 한 초판이 붙여넣기 중단으로 실패했고, 그 대체 경로가 이 사이드카다.

스캔 0건은 실패 — 런북에 해시 선언이 정확히 1건 있어야 한다(0건이면 공허 통과, 2건이면 모호).
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _ROOT / "docs/ops/p3_42_coverage_hint_baseline_live_measurement_runbook.md"
_PROBE = _ROOT / "docs/ops/p3_42_probe.py"
_SHA_DECL = re.compile(r'^\$ProbeSha = "([0-9a-f]{64})"$', re.MULTILINE)


def _probe_bytes_lf() -> bytes:
    # 체크아웃 줄바꿈(CRLF) 영향을 배제한다 — 런북이 받는 것은 git blob(LF)이다.
    return _PROBE.read_bytes().replace(b"\r\n", b"\n")


def test_runbook_declares_exactly_one_probe_sha() -> None:
    assert len(_SHA_DECL.findall(_RUNBOOK.read_text(encoding="utf-8"))) == 1


def test_declared_sha_matches_sidecar_bytes() -> None:
    declared = _SHA_DECL.findall(_RUNBOOK.read_text(encoding="utf-8"))[0]
    actual = hashlib.sha256(_probe_bytes_lf()).hexdigest()
    assert declared == actual, "프로브를 고쳤다면 런북 블록 [C]의 $ProbeSha 도 갱신하라"


def test_sidecar_is_ascii_and_parses() -> None:
    data = _probe_bytes_lf()
    assert all(b < 128 for b in data), "사이드카는 ASCII 전용이다(cp949 경유 사고 예방)"
    ast.parse(data.decode("ascii"))


def test_runbook_gates_d_and_e_on_the_hash() -> None:
    text = _RUNBOOK.read_text(encoding="utf-8")
    # 해시 일치를 가드 조건에 넣은 줄이 D·E 두 곳이어야 한다(조건이 빠지면 변조된 파일을 실행한다).
    assert text.count("($ProbeGot -eq $ProbeSha)") >= 3  # [C] 출력 1 + [D] 가드 1 + [E] 가드 1
    assert "docs/ops/p3_42_probe.py" in text
