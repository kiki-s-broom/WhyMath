"""EOS Core 불투명 페이로드 해석 게이트의 집행·변별력 동결 (ARCH-43 acceptance ②·④).

게이트 스크립트(`scripts/analysis/eos_opaque_payload_gate.py`)는 "무엇이 관측되면 중립성 위반인가"를
먼저 정의했다 — CORE 배정 모듈이 계약이 불투명하다고 선언한 필드(`answer`·`answer_kind`·
`conditions`)의 **값**을 리터럴과 비교·어휘 집합 대조·조회 키·match·문자열 파싱에 쓰면 위반.
이 파일이 하는 일은 넷이다:

1. **실 저장소 동결** — CORE 309모듈(2026-09-06 실측) 스캔이 기준선과 **지문 단위로** 정확히
   일치하는가. 늘면 RED, 줄면 ratchet RED(기준선을 줄여야 통과). 기준선의 정체성은 (모듈, 종류)별
   개수가 아니라 위반 하나하나의 AST 지문이다 — 개수 대조는 "옛 위반 상환 + 같은 모듈에 새 위반"이
   1→1로 상쇄돼 통과한다(PR #1014 Codex P1 · §②′가 그 시나리오를 RED로 동결).
2. **주입 RED** — 위반 6종을 합성 소스로 넣으면 각각 검출되는가. 정상 입력에서 초록인 것은 보호의
   증거가 아니다(CLAUDE.md 2026-09-01). 실 저장소와 **같은 판정 함수**(`scan_source`·`run_gate`·
   `evaluate`)를 쓴다 — 주입용 파서를 따로 두면 그 파서가 통과해도 실 스캔이 통과한다는 뜻이 안 된다.
3. **예외 green** — 같은 패턴이 ADAPTER 배정 모듈(`l4.subject_adapter_math`·`l3.verify_answer`)에
   있으면 정상이다(해석하는 쪽). 예외 목록은 `BOUNDARY_MAP`에서 파생되며 여기서 따로 적지 않는다.
4. **측정 실패 = exit 2** — CORE 0건·파싱 실패는 "위반 없음"이 아니다(스캔 0건은 실패).

축 (c)(계약 시그니처의 수학 은유 식별자)는 §④에서 프로브의 어휘 술어를 재사용해 0건을 동결하고
주입으로 변별력을 확인한다.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "eos_opaque_payload_gate.py"
_PROBE_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "eos_core_boundary_probe.py"
_CONTRACT = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "schema" / "subject_adapter.py"
_BOUNDARY_DOC = _REPO_ROOT / "docs" / "architecture" / "eos_core_adapter_boundary.md"
_SOURCE_ROOT = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# 계약 docstring "불투명 페이로드 원칙" 절이 이름 붙인 필드 — 파생 결과의 동결(바뀌면 계약과 함께 고친다)
EXPECTED_OPAQUE_FIELDS: frozenset[str] = frozenset({"answer", "answer_kind", "conditions"})


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"스크립트 로드 불가: {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.fixture(scope="module")
def gate() -> Any:
    return _load(_GATE_SCRIPT, "_eos_opaque_payload_gate_under_test")


@pytest.fixture(scope="module")
def fields(gate: Any) -> frozenset[str]:
    result: frozenset[str] = gate.opaque_fields_from_contract(_CONTRACT.read_text(encoding="utf-8"))
    return result


@pytest.fixture(scope="module")
def real_result(gate: Any) -> Any:
    return gate.run_gate(_SOURCE_ROOT)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# ① 불투명 필드 — 계약의 기존 규칙에서 파생(이중 진실 원천 금지)
# ──────────────────────────────────────────────────────────────────────


def test_opaque_fields_are_derived_from_the_contract_prose(fields: frozenset[str]) -> None:
    """게이트가 손으로 적은 목록이 아니라 계약 docstring에서 필드를 읽는가 — 결과를 동결한다."""
    assert fields == EXPECTED_OPAQUE_FIELDS, sorted(fields)


def test_derivation_fails_loudly_without_the_section(gate: Any) -> None:
    """절이 없으면 빈 집합으로 조용히 통과하지 않고 타입 있는 예외로 죽는다(측정 실패)."""
    fake = '"""계약.\n\n## 다른 절\n\n`answer_kind`\n"""\nclass ProblemStatement:\n    answer_kind: str\n'
    with pytest.raises(gate.ContractDerivationError, match="불투명 페이로드 원칙"):
        gate.opaque_fields_from_contract(fake)


def test_derivation_fails_when_section_names_no_real_field(gate: Any) -> None:
    fake = (
        '"""계약.\n\n## 불투명 페이로드 원칙\n\n`ghost_field`는 불투명.\n"""\n'
        "class ProblemStatement:\n    answer_kind: str\n"
    )
    with pytest.raises(gate.ContractDerivationError, match="하나도"):
        gate.opaque_fields_from_contract(fake)


# ──────────────────────────────────────────────────────────────────────
# ② 실 저장소 — 분모가 실재하고 위반이 기준선과 정확히 일치한다
# ──────────────────────────────────────────────────────────────────────


def test_real_scan_population_is_real(real_result: Any) -> None:
    """스캔 0건은 실패 — CORE 분모가 실제 규모(2026-09-06 실측 309)와 같은 자릿수여야 한다."""
    assert real_result.scanned > 200, real_result.scanned
    assert real_result.files_total > real_result.scanned
    assert set(real_result.skipped) <= {"ADAPTER", "INFRA", "MIXED"}, real_result.skipped
    assert not real_result.errors, real_result.errors


def test_real_scan_matches_the_baseline_exactly(gate: Any, real_result: Any) -> None:
    """현행 위반 = `l1.problem_bank.populate` membership 1건(EOS-85 소유). 늘면 RED, 줄면 ratchet RED."""
    code, reason = gate.evaluate(real_result)
    assert code == 0, reason
    observed = gate.observed_counts(real_result)
    assert observed == {k: g.count for k, g in gate.KNOWN_VIOLATIONS.items()}, observed
    # 개수만이 아니라 지문까지 — 판정이 실제로 대조하는 키
    assert gate.observed_fingerprints(real_result) == gate.baseline_fingerprints(
        gate.KNOWN_VIOLATIONS
    )


def test_the_former_alias_violation_is_gone(gate: Any, real_result: Any) -> None:
    """종전의 유일 위반(`kind_raw = raw.get("answer_kind")` → `kind_raw in (...)`)이 사라졌다.

    EOS-85가 그 열거를 제거해 지문 `d93b2c7770a0`이 상환됐고 기준선도 함께 비웠다.

    **별칭 탐지력은 여기서 잃지 않는다.** 이 테스트가 원래 지키던 것은 "별칭을 추적하지 않는
    스캐너는 이 형태를 놓치고 0을 낸다"였는데, 그 축은 아래 합성 주입 목록의 *별칭 경유
    (populate 실제 형태)* 항목이 계속 RED로 동결한다 — 실 저장소에 위반이 남아 있어야만
    탐지력을 확인할 수 있는 구조가 아니다(위반을 갚으면 탐지력이 사라지는 테스트는 상환을
    벌주는 셈이 된다).
    """
    assert real_result.violations == [], real_result.violations
    assert gate.KNOWN_VIOLATIONS == {}, gate.KNOWN_VIOLATIONS


def test_baseline_entries_carry_owner_and_recheck(gate: Any) -> None:
    """만료 없는 유예 금지 — 기준선의 모든 항목에 상환 소유 태스크와 재확인 지점이 있어야 한다."""
    for key, g in gate.KNOWN_VIOLATIONS.items():
        assert g.count >= 1, key
        for fp in g.fingerprints:  # 지문 형식 — sha256 앞 12 hex (자리표시자·빈 문자열 금지)
            assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp), (key, fp)
        assert g.owner.strip() and g.recheck.strip(), key
        owner_yaml = _REPO_ROOT / "backlog" / "tasks" / f"{g.owner}.yaml"
        assert owner_yaml.is_file(), f"{key}: 소유 태스크가 대장에 없다 — {g.owner}"
        assert key[1] in gate.VIOLATION_KINDS, key


def test_cli_main_returns_zero_on_the_real_repo(gate: Any, capsys: Any) -> None:
    """CLI 경로(인자 파싱·로그·마크다운)까지 한 번 통과시킨다 — 판정은 exit code."""
    code = gate.main([])
    out = capsys.readouterr()
    assert code == 0, out.err
    # 마크다운 골격이 나왔는가 — 특정 *위반 줄*을 기대하지 않는다(EOS-85로 위반 0건이 됐고,
    # 위반 문자열을 기대하면 상환할 때마다 이 테스트가 깨진다).
    assert "분모: CORE **" in out.out
    assert "## 기준선 (KNOWN_VIOLATIONS)" in out.out


def test_cli_main_exits_2_when_source_root_is_missing(gate: Any, tmp_path: Path) -> None:
    assert gate.main(["--source", str(tmp_path / "nope")]) == 2


# ──────────────────────────────────────────────────────────────────────
# ③ 변별력 — 위반 6종 주입 RED (같은 판정 함수 `scan_source`)
# ──────────────────────────────────────────────────────────────────────

_INJECTIONS: list[tuple[str, str]] = [
    # eq_literal — 속성 읽기 · 좌우 뒤집기 · != · 명명 상수 · 첨자 읽기 · .get 읽기 · 값 보존 메서드
    ('if p.answer_kind == "physics.quantity_with_unit":\n    pass\n', "eq_literal"),
    ('if "quadratic" != p.answer_kind:\n    pass\n', "eq_literal"),
    ("if p.answer_kind == KIND_FINITE:\n    pass\n", "eq_literal"),
    ("if Kind.FINITE == p.answer_kind:\n    pass\n", "eq_literal"),
    ('if payload["answer_kind"] == "x":\n    pass\n', "eq_literal"),
    ('if raw.get("answer_kind") == "x":\n    pass\n', "eq_literal"),
    ('if p.answer_kind.strip().lower() == "x":\n    pass\n', "eq_literal"),
    # membership — 튜플 리터럴 · 명명 집합 · not in · 별칭 경유(populate 실제 형태)
    ('ok = p.answer_kind in ("a", "b")\n', "membership"),
    ("ok = p.answer_kind not in SUPPORTED\n", "membership"),
    (
        'kind_raw = raw.get("answer_kind")\nkind = kind_raw if kind_raw in ("a",) else None\n',
        "membership",
    ),
    ("def f(p):\n    k = p.answer_kind\n    return k in supported\n", "membership"),
    # substring_probe
    ('if "=" in p.conditions:\n    pass\n', "substring_probe"),
    ("if token in p.conditions:\n    pass\n", "substring_probe"),
    # dict_key — 첨자 · .get
    ("handler = HANDLERS[p.answer_kind]\n", "dict_key"),
    ("handler = HANDLERS.get(p.answer_kind)\n", "dict_key"),
    # match
    ('match p.answer_kind:\n    case "x":\n        pass\n    case _:\n        pass\n', "match"),
    # str_parse
    ('parts = p.conditions.split(";")\n', "str_parse"),
    ('if p.answer_kind.startswith("physics."):\n    pass\n', "str_parse"),
    # 별칭이 중첩 함수로 물려받힌다(클로저)
    ("k = p.answer_kind\ndef g():\n    return k == 'x'\n", "eq_literal"),
    # AnnAssign · walrus 별칭
    ("k: str = p.answer_kind\nif k == 'x':\n    pass\n", "eq_literal"),
    ("if (k := p.answer_kind) == 'x':\n    pass\n", "eq_literal"),
]


@pytest.mark.parametrize(("source", "kind"), _INJECTIONS)
def test_scanner_detects_each_injected_violation(
    gate: Any, fields: frozenset[str], source: str, kind: str
) -> None:
    hits = gate.scan_source(source, fields)
    assert [h.kind for h in hits] == [kind], hits


def test_every_violation_kind_is_covered_by_an_injection(gate: Any) -> None:
    """정의한 종류 6종 전부가 주입으로 RED를 낸 적이 있어야 한다 — 검사되지 않은 종류는 정의가 아니다."""
    assert {kind for _, kind in _INJECTIONS} == set(gate.VIOLATION_KINDS)


_NON_VIOLATIONS: list[str] = [
    "if a.answer_kind == b.answer_kind:\n    pass\n",  # 불투명 값끼리 — 구조적 같음
    "if p.conditions:\n    pass\n",  # 진위 — 존재 여부
    "if target.answer is not None:\n    pass\n",  # None 검사 (실 저장소 diag_item_projector 형태)
    "f(p.answer_kind)\n",  # 넘김
    "for c in p.conditions:\n    pass\n",  # 순회
    "dto = Out(kind=p.answer_kind)\n",  # 담기
    "if kind == expected:\n    pass\n",  # 별칭 아닌 소문자 이름끼리 — 판단 불가, 세지 않는다
    'if p.problem_ref == "x":\n    pass\n',  # 불투명 필드가 아닌 필드
    'if status == "pending":\n    pass\n',  # 무관한 비교
    "x = p.answer_kind\n",  # 별칭 정의만, 사용 없음
    'if p.answer_kind == "x":\n    pass\n',  # ← 위반이지만 아래 테스트가 fields를 비워 대조군으로 쓴다
]


@pytest.mark.parametrize("source", _NON_VIOLATIONS[:-1])
def test_scanner_ignores_structural_handling(
    gate: Any, fields: frozenset[str], source: str
) -> None:
    assert gate.scan_source(source, fields) == []


def test_scanner_is_driven_by_the_field_set_not_by_hardcoded_names(gate: Any) -> None:
    """필드 집합을 비우면 위반이 사라져야 한다 — 이름이 스캐너 안에 박혀 있지 않다는 증거."""
    violating = _NON_VIOLATIONS[-1]
    assert gate.scan_source(violating, frozenset({"answer_kind"})) != []
    assert gate.scan_source(violating, frozenset()) == []


# ──────────────────────────────────────────────────────────────────────
# ③′ 끝-끝 — 가짜 소스 트리로 run_gate·evaluate·예외·측정 실패까지 같은 경로로
# ──────────────────────────────────────────────────────────────────────

_VIOLATING_BODY = """
    def choose(p):
        if p.answer_kind == "physics.quantity_with_unit":
            return 1
        return 0
"""
_CLEAN_BODY = """
    def carry(p):
        return p.answer_kind
"""


def test_end_to_end_core_module_violation_is_exit_1_with_location(
    gate: Any, tmp_path: Path
) -> None:
    """CORE 배정 경로(`l2.*`)에 위반을 심으면 exit 1 + 파일:행 + 종류가 나온다."""
    _write(tmp_path, "l2/fake_core.py", _VIOLATING_BODY)
    _write(tmp_path, "l2/clean.py", _CLEAN_BODY)
    result = gate.run_gate(tmp_path)
    assert result.scanned == 2 and not result.errors
    code, reason = gate.evaluate(result, baseline={})
    assert code == 1, reason
    [v] = result.violations
    assert (v.module, v.kind, v.lineno) == ("l2.fake_core", "eq_literal", 3)
    assert v.path.endswith("l2/fake_core.py")


def test_end_to_end_same_pattern_in_adapter_modules_is_exit_0(gate: Any, tmp_path: Path) -> None:
    """ADAPTER 배정(`l4.subject_adapter_math`·`l3.verify_answer`)은 해석하는 쪽 — 예외이며 초록.

    예외 목록을 여기서 적지 않는다: `BOUNDARY_MAP`이 ADAPTER로 배정한 경로를 그대로 쓴다.
    """
    _write(tmp_path, "l4/subject_adapter_math.py", _VIOLATING_BODY)
    _write(tmp_path, "l3/verify_answer.py", _VIOLATING_BODY)
    _write(tmp_path, "l2/clean.py", _CLEAN_BODY)  # 분모 0을 피하기 위한 깨끗한 CORE 1건
    result = gate.run_gate(tmp_path)
    assert result.scanned == 1 and result.skipped == {"ADAPTER": 2}, result
    code, reason = gate.evaluate(result, baseline={})
    assert code == 0, reason
    assert result.violations == []


def test_end_to_end_mixed_and_infra_are_excluded_from_the_denominator(
    gate: Any, tmp_path: Path
) -> None:
    _write(tmp_path, "l3/dsl/compiler.py", _VIOLATING_BODY)  # MIXED
    _write(tmp_path, "ops/probe.py", _VIOLATING_BODY)  # INFRA
    _write(tmp_path, "l2/clean.py", _CLEAN_BODY)
    result = gate.run_gate(tmp_path)
    assert result.skipped == {"MIXED": 1, "INFRA": 1} and result.violations == []


def test_end_to_end_zero_core_modules_is_exit_2_not_pass(gate: Any, tmp_path: Path) -> None:
    """스캔 0건은 실패 — INFRA만 있는 트리는 '위반 없음'이 아니라 측정 실패다."""
    _write(tmp_path, "ops/only_infra.py", _CLEAN_BODY)
    result = gate.run_gate(tmp_path)
    assert result.scanned == 0
    code, reason = gate.evaluate(result, baseline={})
    assert code == 2 and "0건" in reason, reason


def test_end_to_end_empty_tree_is_exit_2(gate: Any, tmp_path: Path) -> None:
    code, reason = gate.evaluate(gate.run_gate(tmp_path), baseline={})
    assert code == 2, reason


def test_end_to_end_parse_failure_is_exit_2_with_the_exception_type(
    gate: Any, tmp_path: Path
) -> None:
    """파싱 실패는 타입명과 함께 남고 exit 2 — 위반이 0이어도 통과가 아니다(침묵 실패 금지)."""
    _write(tmp_path, "l2/broken.py", "def f(:\n    pass\n")
    _write(tmp_path, "l2/clean.py", _CLEAN_BODY)
    result = gate.run_gate(tmp_path)
    assert len(result.errors) == 1 and "SyntaxError" in result.errors[0], result.errors
    assert result.violations == []
    code, reason = gate.evaluate(result, baseline={})
    assert code == 2 and "파싱" in reason, reason


def test_end_to_end_ratchet_fails_when_baseline_is_stale(gate: Any, tmp_path: Path) -> None:
    """기준선이 남아 있는데 위반이 사라졌으면 exit 1(RATCHET) — 갚은 빚의 유예 줄이 조용히 남지 않는다."""
    _write(tmp_path, "l2/clean.py", _CLEAN_BODY)
    stale = {("l2.clean", "eq_literal"): gate.Grandfathered(("0" * 12,), "X", "Y")}
    code, reason = gate.evaluate(gate.run_gate(tmp_path), baseline=stale)
    assert code == 1 and "RATCHET" in reason, reason


def test_end_to_end_growth_beyond_baseline_is_exit_1(gate: Any, tmp_path: Path) -> None:
    """같은 (모듈, 종류)라도 건수가 늘면 RED — 기준선은 상한이지 면허가 아니다."""
    _write(
        tmp_path, "l2/fake_core.py", _VIOLATING_BODY + _VIOLATING_BODY.replace("choose", "again")
    )
    result = gate.run_gate(tmp_path)
    assert len(result.violations) == 2
    first = result.violations[0].fingerprint
    one = {("l2.fake_core", "eq_literal"): gate.Grandfathered((first,), "X", "Y")}
    code, reason = gate.evaluate(result, baseline=one)
    assert code == 1 and "기준선 밖" in reason, reason
    assert result.violations[1].fingerprint in reason, reason  # 어느 자리가 새것인지 지목한다


# ──────────────────────────────────────────────────────────────────────
# ②′ 기준선 정체성 = 지문 — 개수 대조의 상쇄 우회를 RED로 동결 (PR #1014 Codex P1)
# ──────────────────────────────────────────────────────────────────────

_OLD_SITE = """
    def choose(p):
        if p.answer_kind == "physics.quantity_with_unit":
            return 1
        return 0
"""
_NEW_SITE = """
    def other(p):
        if p.answer_kind == "chemistry.molar_mass":
            return 2
        return 0
"""


def _fingerprinted_baseline(gate: Any, result: Any) -> dict[tuple[str, str], Any]:
    """관측된 위반 전부를 그대로 기준선으로 등재한다(테스트용 — 실 기준선은 사람이 옮겨 적는다)."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for v in result.violations:
        grouped.setdefault((v.module, v.kind), []).append(v.fingerprint)
    return {k: gate.Grandfathered(tuple(fps), "X", "Y") for k, fps in grouped.items()}


def test_baseline_is_per_violation_identity_not_a_count(gate: Any, tmp_path: Path) -> None:
    """옛 위반을 갚으면서 같은 모듈·같은 종류에 새 위반을 하나 넣으면 (모듈, 종류) 개수는 1→1이다.

    개수 기준선이면 exit 0으로 통과한다(상환과 신규 위반이 상쇄 — Codex P1). 지문 기준선은 신규
    자리를 "기준선 밖"으로 잡고 옛 자리는 RATCHET으로 잡는다 — 두 신호 중 신규가 먼저 난다.
    """
    _write(tmp_path, "l2/fake_core.py", _OLD_SITE)
    before = gate.run_gate(tmp_path)
    baseline = _fingerprinted_baseline(gate, before)
    assert gate.evaluate(before, baseline=baseline)[0] == 0

    _write(tmp_path, "l2/fake_core.py", _NEW_SITE)  # 옛 자리 제거 + 새 자리 추가(같은 모듈·종류)
    after = gate.run_gate(tmp_path)
    assert gate.observed_counts(after) == gate.observed_counts(before)  # 개수는 상쇄돼 같다
    code, reason = gate.evaluate(after, baseline=baseline)
    assert code == 1 and "기준선 밖" in reason, reason
    assert after.violations[0].fingerprint in reason and "fake_core.py:3" in reason, reason


def test_baseline_fingerprint_survives_line_moves(gate: Any, tmp_path: Path) -> None:
    """줄 번호는 정체성이 아니다 — 위에 코드가 끼어들어 행이 밀려도 같은 식이면 같은 지문·exit 0."""
    _write(tmp_path, "l2/fake_core.py", _OLD_SITE)
    before = gate.run_gate(tmp_path)
    baseline = _fingerprinted_baseline(gate, before)

    # 주석은 _OLD_SITE와 같은 들여쓰기로 — _write의 dedent가 공통 들여쓰기를 유지하게
    shifted = "\n    # 주석 세 줄이\n    # 행 번호를\n    # 밀어낸다\n" + _OLD_SITE
    _write(tmp_path, "l2/fake_core.py", shifted)
    after = gate.run_gate(tmp_path)
    assert after.violations[0].lineno != before.violations[0].lineno
    assert after.violations[0].fingerprint == before.violations[0].fingerprint
    assert gate.evaluate(after, baseline=baseline)[0] == 0


def test_baseline_fingerprint_changes_when_the_expression_changes(
    gate: Any, tmp_path: Path
) -> None:
    """같은 자리라도 해석 식이 바뀌면(어휘 추가 등) 다른 지문 — 유예를 다시 받아야 한다."""
    _write(tmp_path, "l2/fake_core.py", _OLD_SITE)
    baseline = _fingerprinted_baseline(gate, gate.run_gate(tmp_path))

    widened = _OLD_SITE.replace(
        '== "physics.quantity_with_unit"', 'in ("physics.quantity_with_unit", "x")'
    )
    _write(tmp_path, "l2/fake_core.py", widened)
    code, reason = gate.evaluate(gate.run_gate(tmp_path), baseline=baseline)
    assert code == 1 and "기준선 밖" in reason, reason


def test_duplicate_expressions_are_counted_per_fingerprint(gate: Any, tmp_path: Path) -> None:
    """동일 식이 두 자리에 있으면 지문이 같다 — 기준선에 한 번만 적으면 두 번째는 '증가'로 RED."""
    _write(tmp_path, "l2/fake_core.py", _OLD_SITE + _OLD_SITE.replace("choose", "again"))
    result = gate.run_gate(tmp_path)
    fps = [v.fingerprint for v in result.violations]
    assert len(fps) == 2 and fps[0] == fps[1]
    once = {("l2.fake_core", "eq_literal"): gate.Grandfathered((fps[0],), "X", "Y")}
    assert gate.evaluate(result, baseline=once)[0] == 1
    twice = {("l2.fake_core", "eq_literal"): gate.Grandfathered((fps[0], fps[0]), "X", "Y")}
    assert gate.evaluate(result, baseline=twice)[0] == 0


def test_cli_end_to_end_on_a_fake_tree(gate: Any, tmp_path: Path, capsys: Any) -> None:
    """`--source`·`--json` 경로로 exit 1과 JSON 산출을 확인 — 실패해도 증거가 남는가."""
    _write(tmp_path / "src", "l2/fake_core.py", _VIOLATING_BODY)
    out_json = tmp_path / "out.json"
    code = gate.main(["--source", str(tmp_path / "src"), "--json", str(out_json)])
    assert code == 1
    assert out_json.is_file()
    payload = out_json.read_text(encoding="utf-8")
    assert '"exit": 1' in payload and '"eq_literal"' in payload
    assert '"fingerprint": "' in payload  # 기준선에 옮겨 적을 값이 산출에 남는다
    captured = capsys.readouterr()
    assert "fake_core.py:3" in captured.out


# ──────────────────────────────────────────────────────────────────────
# ④ 축 (c) — 계약 시그니처의 수학 은유 식별자 0건 동결 + 주입 (어휘 술어는 프로브가 단일 원천)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def is_math() -> Any:
    return _load(_PROBE_SCRIPT, "_eos_core_boundary_probe_for_gate_test")._identifier_is_math


def test_contract_signature_identifiers_carry_no_math_vocabulary(gate: Any, is_math: Any) -> None:
    """EOS-66 ④(반례 검증: 시그니처에 LaTeX·SymPy류 유출 없음)의 기계화 — 현행 0건을 동결한다."""
    idents = gate.contract_identifiers(_CONTRACT.read_text(encoding="utf-8"))
    assert len(idents) >= 20, idents  # 스캔 0건 방지 — 4 DTO·Protocol·메서드 3·인자·필드 15
    hits = [(ln, role, name, is_math(name)) for ln, role, name in idents if is_math(name)]
    assert hits == [], hits


@pytest.mark.parametrize(
    ("source", "expect"),
    [
        (
            "class SubjectAdapter:\n    def parse_latex(self, expr: str) -> str: ...\n",
            "parse_latex",
        ),
        ("class ProblemStatement:\n    sympy_expr: str\n", "sympy_expr"),
        (
            "class SubjectAdapter:\n    def f(self, integral_bounds: str) -> str: ...\n",
            "integral_bounds",
        ),
    ],
)
def test_contract_identifier_scan_detects_injected_math_metaphor(
    gate: Any, is_math: Any, source: str, expect: str
) -> None:
    idents = gate.contract_identifiers(source)
    flagged = [name for _, _, name in idents if is_math(name)]
    assert flagged == [expect], idents


def test_contract_identifier_scan_admits_it_cannot_see_prose(gate: Any, is_math: Any) -> None:
    """정직한 공백 — EOS-92 §2-1의 '치환맵' 은유는 docstring 산문이라 이 축이 못 본다."""
    src = 'class SubjectAdapter:\n    def evaluate_answer(self, answer):\n        """변수명→값 치환맵."""\n'
    assert [n for _, _, n in gate.contract_identifiers(src) if is_math(n)] == []


# ──────────────────────────────────────────────────────────────────────
# ⑤ 정본 문서 배선 — 계약과 경계 문서가 이 게이트를 가리키는가
# ──────────────────────────────────────────────────────────────────────


def test_contract_limit_section_points_at_this_gate() -> None:
    """계약의 '래칫의 한계' 절이 '기계 집행은 현재 없다'에서 이 게이트로 갱신됐는가 — 있는 척도, 없는 척도 금지."""
    doc = _CONTRACT.read_text(encoding="utf-8")
    assert "eos_opaque_payload_gate.py" in doc
    assert "ARCH-43" in doc


def test_boundary_doc_records_the_gate() -> None:
    doc = _BOUNDARY_DOC.read_text(encoding="utf-8")
    assert "eos_opaque_payload_gate.py" in doc and "ARCH-43" in doc
