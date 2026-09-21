"""EOS Core 경계 계측 2종 동결 — 전이 도달 잔여 누수 · 리터럴 금지 규칙 (EOS-84 acceptance ③).

계측기(`eos_core_boundary_probe.py`)는 위반 수로 exit 1을 내지 않는다. **게이트는 여기다**:

1. **리터럴 비교 기준선 동결** — CORE 모듈의 `== "math"`·`in ("quadratic", …)`류는 현재 **1건**
   (`l1.problem_bank.populate._verify_meta_from_raw`가 answer_kind 17종을 튜플로 열거 — EOS-66의
   "answer_kind는 Core가 해석하지 않는 불투명 문자열" 계약과 충돌하는 진성 경계 냄새). 새 위치가
   생기면 RED, 그 1건이 어댑터/데이터로 빠지면 기준선을 비워 ratchet한다. 계획서 100 §3.7의
   금지 규칙을 글자 그대로 집행하되, 이미 있던 위반을 0으로 위장하지 않는다.
2. **잔여 누수 집합 동결** — 합성 루트를 막아도 ADAPTER에 닿는 CORE 출발점은 여전히 **2건**
   이지만 [EOS-86·2026-09-06] **누수 지점이 바뀌었다**: 이전엔 `l4.solution_coaching`(MIXED)이
   `l3.verify_solution`을 직접 import해 그 자리에서 막혔다. EOS-86이 그 직접 import를
   `StepChainVerifier` 선택층 주입(기본 구현은 합성 루트 경유)으로 교체해 solution_coaching
   경유 경로는 실제로 0이 됐다(BFS로 실측 확인) — 그런데 최단 경로가 사라지자 BFS가 그보다
   *더 긴, 지금까지 가려져 있던* 경로를 찾아냈다: `api.coach`/`api.ocr_handoff` → … →
   `harness.wh1_loop`(INFRA — `l3.verify_solution`·`l4.misconception.*`를 직접 import) →
   ADAPTER. `harness`는 `composition`과 달리 DESIGNED_SEAMS가 아니라서(§경계문서 — "상위 계층
   호출이 정상이라 계층 계약 밖"으로만 취급되지 실제 교체점은 아니다) 이 경로를 막지 않는다.
   **판정**: 이 누수는 EOS-86이 만든 것이 아니라 *원래 있었고 더 짧은 경로에 가려 안 보였던*
   것이다(솔직한 실측 — acceptance ③ 원문의 "0건" 기대와 다르다·후속 태스크로 분리 등재).
   늘면 RED, 줄면 이 집합을 줄여 ratchet한다. 키는 (출발점, 누수 지점)이다 — 끝 ADAPTER는
   동률이 있어 열쇠로 쓰면 BFS 순서에 따라 흔들린다.
3. **변별력** — 스캐너에 결함을 실제로 주입해(가짜 소스·가짜 그래프) 검출되는지 확인한다. 정상
   입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 2026-09-01).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "eos_core_boundary_probe.py"
_BOUNDARY_DOC = _REPO_ROOT / "docs" / "architecture" / "eos_core_adapter_boundary.md"

# 리터럴 비교 기준선 — (CORE 모듈, 위반 종류) → 허용 건수. 줄이는 방향으로만 고친다.
# EOS-85로 **0이 됐다**(2026-09-06 · 판정 기준 main dc2e6583). 마지막 1건은
# `l1/problem_bank/populate.py`가 수학 `answer_kind` 17종을 튜플로 열거하던 자리였고,
# 그 열거를 불투명 문자열 통과로 바꾸면서 사라졌다. 기준선은 이제 **비어 있다** — 유예 0.
# (아래 테스트는 "줄었으면 ratchet하라"고 RED를 내므로, 이 dict를 비우지 않으면
#  0건 실측 자체가 실패로 보고된다 — 기준선은 실측을 따라 내려간다.)
#
# ⚠ **이 0이 무엇을 보장하고 무엇을 보장하지 않는가**(EOS-85 실측·과대주장 방지):
# 스캐너는 비교문의 문자열 리터럴을 `MATH_TYPE_RX`(quadratic|trig*|probability|inequality …
# 접두 목록)로 판정한다. 위 17종 중 **그 정규식에 걸리는 것은 `inequality_direction` 하나뿐**
# 이었다 — 즉 원래의 히트 1건은 사실상 그 한 값이 만들었다. 결함 주입으로 확인했다:
# 화이트리스트를 3종·7종으로 되살려도(`inequality_direction` 제외) 히트는 **0으로 유지되고
# 이 테스트는 통과한다**. 그러므로 "리터럴 비교 0"은 *접두 목록에 걸리는 어휘*가 없다는 뜻이지
# 과목 어휘 열거가 전부 사라졌다는 뜻이 아니다.
# 이 사각의 소유자는 `EOS-01` acceptance ②(매처 확장)이며, 그때까지 `answer_kind` 축의
# 실질 보호는 행동 축 회귀 테스트가 맡는다
# (`tests/backend/l1/problem_bank/test_populate.py::test_load_passes_unknown_answer_kind_through_verbatim`
#  — 같은 뮤테이션에서 실제로 RED가 났다).
LITERAL_COMPARE_BASELINE: dict[tuple[str, str], int] = {}

# CORE가 과목 전용 **enum 멤버**를 열거하는 자리 — (모듈, 참조). EOS-90에서 v1의 사각으로
# 드러났다(문자열이 하나도 없어 리터럴 비교 스캔을 그대로 통과했다).
SUBJECT_ENUM_MEMBER_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("l4.visualization_policy", "VisualizationStyle.수직선"),
        ("l4.visualization_policy", "VisualizationStyle.접선도함수"),
    }
)

# 과목 어휘가 **필드명**에 박힌 자리 — (모듈, 필드). 값이 아니라 이름이라 어휘 스캔이 못 봤다.
MATH_FIELD_NAME_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("l3.solution_path", "sympy_verified"),
        ("l4.misconception.catalog", "_TRIG"),
        ("schema.visualization", "tangent_point"),
        ("schema.visualization", "integral_region"),
        ("schema.visualization", "show_extrema"),
        ("schema.visualization", "number_line"),
    }
)

# 잔여 누수 동결 — (CORE 출발점, ADAPTER 직전의 누수 지점). 줄이는 방향으로만 고친다.
# [EOS-86·2026-09-06] l4.solution_coaching은 더 이상 누수 지점이 아니다(verify_solution·
# wrong_form_match 직접 import 제거 — StepChainVerifier 선택층 주입으로 교체). 그러나 그
# 최단 경로가 사라지자 BFS가 더 긴 기존 경로를 드러냈다 — harness.wh1_loop(INFRA)가
# l3.verify_solution을 직접 import해 같은 두 출발점(api.coach·api.ocr_handoff)이 여전히
# ADAPTER에 닿는다(모듈 상단 §2 상세). EOS-86 범위 밖(별도 후속 태스크)이라 그대로 동결한다.
RESIDUAL_LEAK_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("api.coach", "harness.wh1_loop"),
        ("api.ocr_handoff", "harness.wh1_loop"),
    }
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("_eos_core_boundary_probe_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def probe() -> Any:
    return _load()


@pytest.fixture(scope="module")
def result(probe: Any) -> dict[str, Any]:
    return probe.run_probe(lambda _msg: None)


# ──────────────────────────────────────────────────────────────────────
# ① 게이트 — 실측이 동결값을 넘지 않는가
# ──────────────────────────────────────────────────────────────────────


def test_population_is_real(result: dict[str, Any]) -> None:
    assert result["core"] > 200 and result["adapter"] > 50, result


def test_core_literal_compares_do_not_exceed_baseline(result: dict[str, Any]) -> None:
    """계획서 100 §3.7 — `if subject == "math"` · `if problem.type == "quadratic"`는 Core 위반.

    기준선 밖의 (모듈, 종류)가 하나라도 생기거나 같은 자리의 건수가 늘면 RED. 기준선보다 줄면
    기준선을 갱신하라고 실패시킨다(ratchet) — 고쳐 놓고 게이트가 느슨한 채 남는 것을 막는다.
    """
    observed: dict[tuple[str, str], int] = {}
    for module, hits in result["literal_compares"].items():
        for h in hits:
            observed[(module, h["kind"])] = observed.get((module, h["kind"]), 0) + 1
    new_or_grown = {k: n for k, n in observed.items() if n > LITERAL_COMPARE_BASELINE.get(k, 0)}
    assert not new_or_grown, f"CORE 리터럴 비교 위반(기준선 초과): {new_or_grown}"
    if observed != LITERAL_COMPARE_BASELINE:
        pytest.fail(f"리터럴 비교가 줄었다 — LITERAL_COMPARE_BASELINE을 {observed}로 ratchet")


def test_subject_literal_compares_are_absent_from_core(result: dict[str, Any]) -> None:
    """과목명 분기(`== "math"`)는 기준선조차 두지 않는다 — 0이 아니면 즉시 RED."""
    subject_hits = {
        m: [h for h in hits if h["kind"] == "subject"]
        for m, hits in result["literal_compares"].items()
    }
    subject_hits = {m: v for m, v in subject_hits.items() if v}
    assert subject_hits == {}, f"CORE 과목명 리터럴 비교: {subject_hits}"


def test_residual_transitive_leaks_are_frozen_and_only_shrink(result: dict[str, Any]) -> None:
    observed = {(x["source"], x["path"][-2]) for x in result["reach_residual"]}
    for x in result["reach_residual"]:
        assert len(x["path"]) >= 2, f"ADAPTER 직접 import는 EOS-67이 막는다 — 잔여 경로가 1홉: {x}"
    assert (
        observed <= RESIDUAL_LEAK_BASELINE
    ), f"신규 잔여 누수: {observed - RESIDUAL_LEAK_BASELINE}"
    if observed < RESIDUAL_LEAK_BASELINE:
        pytest.fail(f"잔여 누수가 줄었다 — RESIDUAL_LEAK_BASELINE을 {sorted(observed)}로 ratchet")


def test_every_non_residual_reach_passes_the_designed_seam(result: dict[str, Any]) -> None:
    """교체점(composition)을 지나지 않는 도달은 전부 잔여 누수 목록에 있어야 한다 — 누수가 '정상'으로
    분류되는 세 번째 범주가 생기면 안 된다."""
    residual_sources = {x["source"] for x in result["reach_residual"]}
    for x in result["reach_all"]:
        assert x["via_designed_seam"] or x["source"] in residual_sources, x


def test_math_removal_leaves_most_of_core_standing(result: dict[str, Any]) -> None:
    """'수학을 제거했을 때 무엇이 남는가' — CORE의 90% 이상이 ADAPTER 없이도 import 가능해야 한다."""
    assert result["survivors_after_math_removal"] / result["core"] >= 0.90, result["core"]


@pytest.mark.parametrize(
    "identifier",
    ["trigger", "triggers", "TRIGGERS", "triggered", "coaching_trigger", "LoopEdge.TRIGGERS"],
)
def test_trigger_family_is_not_math(probe: Any, identifier: str) -> None:
    """`trigger` 계열은 수학이 아니다 — 종전 `trig\\w*`가 부분매치하던 거짓 양성(2회차).

    1회차(EOS-86·2026-09-06)는 오탐을 **baseline에 등재해** 덮었고, 그래서 2회차
    (EOS-100·2026-09-16 · `LoopEdge.TRIGGERS`)를 못 막았다. 대책을 데이터가 아니라 코드에
    둔 것이 `trig(?!ger)\\w*`이며, 이 테스트가 그 음성 판정을 동결한다.
    """
    assert probe._identifier_is_math(identifier.split(".")[-1]) is None
    assert probe.MATH_TYPE_RX.match(identifier.split(".")[-1]) is None


@pytest.mark.parametrize(
    ("identifier", "why"),
    [
        ("trig", "trig"),
        ("TRIG", "TRIG"),
        ("trigonometric", "trigonometric"),
        ("trig_identity", "trig"),
        ("_TRIG", "TRIG"),
    ],
)
def test_real_trigonometry_identifiers_still_detected(
    probe: Any, identifier: str, why: str
) -> None:
    """성공 방향 대조군 — 부정 전방탐색이 삼각함수 어휘까지 끄면 과잉 수정이다."""
    assert probe._identifier_is_math(identifier) == why


def test_subject_enum_members_in_core_are_frozen(result: dict[str, Any]) -> None:
    """CORE가 과목 전용 enum 멤버를 여는 자리는 늘 수 없다 — 줄면 기준선을 줄여 ratchet."""
    observed = {(m, h["ref"]) for m, hits in result["subject_enum_members"].items() for h in hits}
    new_hits = observed - SUBJECT_ENUM_MEMBER_BASELINE
    assert not new_hits, f"CORE가 새로 과목 enum 멤버를 열거한다: {sorted(new_hits)}"
    if observed < SUBJECT_ENUM_MEMBER_BASELINE:
        pytest.fail(f"줄었다 — SUBJECT_ENUM_MEMBER_BASELINE을 {sorted(observed)}로 ratchet")


def test_math_field_names_in_core_are_frozen(result: dict[str, Any]) -> None:
    """과목 어휘가 필드명에 박힌 자리 동결 — Core가 그 필드의 *의미*를 아는 지점이다."""
    observed = {(m, h["field"]) for m, hits in result["math_field_names"].items() for h in hits}
    new_hits = observed - MATH_FIELD_NAME_BASELINE
    assert not new_hits, f"CORE에 새 수학 필드명: {sorted(new_hits)}"
    if observed < MATH_FIELD_NAME_BASELINE:
        pytest.fail(f"줄었다 — MATH_FIELD_NAME_BASELINE을 {sorted(observed)}로 ratchet")


# ──────────────────────────────────────────────────────────────────────
# ② 변별력 — 결함 주입
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ('if subject == "math":\n    pass\n', "subject"),
        ('if problem.type == "quadratic":\n    pass\n', "math_type"),
        ('ok = kind in ("linear", "other")\n', "math_type"),
        (
            'match kind:\n    case "trig_identity":\n        pass\n    case _:\n        pass\n',
            "math_type",
        ),
        ('if "수학" == subject_id:\n    pass\n', "subject"),
    ],
)
def test_literal_scanner_detects_injected_violation(probe: Any, source: str, kind: str) -> None:
    hits = probe.scan_literal_compares(source)
    assert len(hits) == 1 and hits[0].kind == kind, hits


@pytest.mark.parametrize(
    "source",
    [
        "if subject == other_subject:\n    pass\n",  # 변수 대 변수 — 리터럴 아님
        'x = "math"\n',  # 대입은 비교가 아니다(③ 어휘 스캔의 영역)
        '"""quadratic in a docstring"""\nif a == "apple":\n    pass\n',
        'if status == "pending":\n    pass\n',
    ],
)
def test_literal_scanner_ignores_non_violations(probe: Any, source: str) -> None:
    assert probe.scan_literal_compares(source) == []


def test_vocabulary_scanner_skips_docstrings_but_catches_data(probe: Any) -> None:
    src = '"""이차방정식을 다루는 모듈 — docstring은 제외."""\nLABEL = "이차함수"\n\n\ndef f():\n    """삼각함수 docstring"""\n    return "LaTeX 본문"\n'
    words = probe.scan_math_vocabulary(src)
    assert [t for _, t in words] == ["이차함수", "LaTeX 본문"], words


@pytest.mark.parametrize(
    ("source", "expect"),
    [
        ("S = {VisualizationStyle.수직선}\n", "VisualizationStyle.수직선"),
        ("x = Style.접선도함수\n", "Style.접선도함수"),
        ("y = Kind.tangent\n", "Kind.tangent"),
    ],
)
def test_enum_member_scanner_detects_injected_subject_knowledge(
    probe: Any, source: str, expect: str
) -> None:
    hits = probe.scan_subject_enum_members(source)
    assert len(hits) == 1 and hits[0][1] == expect, hits


@pytest.mark.parametrize(
    "source",
    [
        "self.tangent = 1\n",  # 소문자 수신자 = 인스턴스 속성, enum 열거가 아니다
        "obj.integral_region\n",
        "S = {Status.pending}\n",  # 과목 무관 enum
        'x = "quadratic"\n',  # 문자열은 리터럴 스캐너 영역
    ],
)
def test_enum_member_scanner_ignores_non_violations(probe: Any, source: str) -> None:
    assert probe.scan_subject_enum_members(source) == []


@pytest.mark.parametrize(
    ("source", "expect"),
    [
        ("tangent_point: float\n", "tangent_point"),
        ("integral_region: str | None = None\n", "integral_region"),
        ("show_extrema: bool = False\n", "show_extrema"),
        ("number_line: object = None\n", "number_line"),
        ("수직선_옵션: int = 0\n", "수직선_옵션"),
    ],
)
def test_field_name_scanner_detects_injected_math_names(
    probe: Any, source: str, expect: str
) -> None:
    hits = probe.scan_math_field_names(source)
    assert len(hits) == 1 and hits[0][1] == expect, hits


@pytest.mark.parametrize(
    "source",
    [
        "created_at: int = 0\n",
        "point_count: int = 0\n",  # point는 일반어 — 단독으로 잡지 않는다
        "line_number: int = 0\n",  # number_line과 토큰은 같지만 복합어가 아니다
        "tangent_point = 1\n",  # 선언(AnnAssign)이 아닌 대입은 세지 않는다(중복 계상 방지)
    ],
)
def test_field_name_scanner_ignores_non_violations(probe: Any, source: str) -> None:
    assert probe.scan_math_field_names(source) == []


def test_enum_scanner_admits_what_it_cannot_see(probe: Any) -> None:
    """정직한 공백 — 어휘 목록 기반이라 목록에 없는 과목 어휘는 **놓친다**.

    `l4.visualization_policy`는 수학 전용 표상 7종을 열거하는데 스캐너는 그중 2종만 잡는다
    (`단위원`·`함수그래프`·`부등식영역`·`분포곡선`·`확률시뮬레이션`은 VOCAB_KO에 없다). 이
    테스트는 그 한계를 **명시적으로 고정**한다 — 놓치는 것을 모르는 채 "0건"이라 말하지 않기
    위해서다. 목록을 넓히면 이 테스트가 실패하고, 그때 기준선도 함께 넓힌다.
    """
    missed = "S = {VisualizationStyle.단위원, VisualizationStyle.분포곡선}\n"
    assert probe.scan_subject_enum_members(missed) == []


def test_reach_detects_an_injected_indirect_edge(probe: Any) -> None:
    """CORE→INFRA→ADAPTER 경유 간선을 가짜 그래프에 넣으면 잡히고, 교체점 경유는 잔여에서 빠진다."""
    graph = {
        "l2.bkt": {"ops.helper"},
        "ops.helper": {"l3.symbolic_equivalence"},
        "l4.polya.engine": {"composition"},
        "composition": {"l4.subject_adapter_math"},
        "l2.irt": {"schema.enums"},
    }
    verdict = {
        "l2.bkt": "CORE",
        "ops.helper": "INFRA",
        "l3.symbolic_equivalence": "ADAPTER",
        "l4.polya.engine": "CORE",
        "composition": "INFRA",
        "l4.subject_adapter_math": "ADAPTER",
        "l2.irt": "CORE",
        "schema.enums": "MIXED",
    }
    all_hits, residual = probe.transitive_reach(
        ["l2.bkt", "l4.polya.engine", "l2.irt"], graph, verdict
    )
    assert {r.source for r in all_hits} == {"l2.bkt", "l4.polya.engine"}
    assert {r.source for r in residual} == {"l2.bkt"}, residual
    assert next(r for r in all_hits if r.source == "l4.polya.engine").via_designed_seam


def test_bfs_tie_break_is_deterministic_across_hash_seeds(probe: Any) -> None:
    """같은 깊이의 ADAPTER가 둘이면 항상 사전순 첫 것으로 끝나야 한다 — set 순회 비결정성 회귀 방어.

    이웃 집합을 여러 삽입 순서로 만들어도 결과가 같아야 한다(set 순서는 삽입·해시에 따라 바뀐다).
    """
    verdict = {"a": "CORE", "m": "MIXED", "z_adapter": "ADAPTER", "b_adapter": "ADAPTER"}
    for order in (["z_adapter", "b_adapter"], ["b_adapter", "z_adapter"]):
        graph = {"a": {"m"}, "m": set(order)}
        assert probe.first_adapter_path("a", graph, verdict) == ("m", "b_adapter"), order


def test_probe_fails_loudly_when_core_population_is_empty(probe: Any, monkeypatch: Any) -> None:
    inv = probe._load_inventory()
    monkeypatch.setattr(inv, "_backend_modules", lambda: [])
    monkeypatch.setattr(probe, "_load_inventory", lambda: inv)
    with pytest.raises(RuntimeError, match="CORE 모듈 0"):
        probe.run_probe(lambda _msg: None)


# ──────────────────────────────────────────────────────────────────────
# ③ 정본 문서 배선
# ──────────────────────────────────────────────────────────────────────


def test_boundary_doc_records_the_measurement_and_points_at_the_probe() -> None:
    doc = _BOUNDARY_DOC.read_text(encoding="utf-8")
    assert "eos_core_boundary_probe.py" in doc
    assert "수학을 제거했을 때" in doc and "잔여 누수" in doc
