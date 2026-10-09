"""SLO 문서 ↔ 코드 드리프트 동결 — OPS-04 (hermetic·라이브 인프라 0).

이 테스트가 막는 것
-------------------
런북·SLO 문서는 *읽는 사람이 그대로 믿고 행동하는* 산출물이다. 그런데 문서는 코드와
달리 컴파일되지 않아서, 코드에서 임계를 바꾸거나 라우트를 지워도 문서는 조용히 옛말을
계속한다. 그 상태의 런북은 "검증 없는 실행 안내"(CLAUDE.md 금기)가 된다. 그래서 두 축을
기계로 동결한다:

1. **임계 수치 일치** — `docs/standards/incident_response_slo.md` §1-5 [기계 판독] 계약
   블록의 기재값이 `Settings`의 **필드 기본값**·`l3.router.SLA_GATE_MS`와 일치하는가.
   인스턴스(`Settings()`)가 아니라 `model_fields[...].default`를 정본으로 읽는 이유:
   인스턴스는 env(`WHYMATH_*`)·.env에 오염돼 "그 머신에서만 통과하는" 테스트가 된다.
   기본값 대조는 환경과 무관하게 항상 같은 판정을 낸다(hermetic).

2. **경로 실재** — 문서가 안내하는 엔드포인트가 실제 `create_app()` 라우트 표에 있는가.
   없는 경로를 안내하는 런북(장애 중에 오타 URL을 두드리게 만드는 문서)을 원천 차단한다.

침묵 실패 방지 (이 테스트 자신에 대한 규율)
--------------------------------------------
"아무것도 못 찾았으니 위반도 없다"는 통과는 검증이 아니라 위장이다. 그래서 파서는
①계약 블록 자체가 없으면 ②기대 키가 블록 안에 없으면 ③블록에 모르는 키가 있으면
전부 *불일치로 보고*한다. 이 규율은 `test_missing_contract_block_is_not_silently_passed`
와 `test_mutated_threshold_is_actually_detected`로 다시 동결한다 — 변별력 없는 검증 스텝 금지
(CLAUDE.md, 2026-07-17 logconfig `delay:true` 사고 선례).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from whymath_backend.app import RouteLatencyBody
from whymath_backend.config import Settings
from whymath_backend.l3.router import SLA_GATE_MS
from whymath_backend.ops import uptime_probe
from whymath_backend.ops.declared_unwired_audit import route_paths
from whymath_backend.ops.service_health import ServiceMetrics

# 레포 루트 — tests/backend/ops/<이 파일> 기준 3단계 위.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SLO_DOC = _REPO_ROOT / "docs" / "standards" / "incident_response_slo.md"

# 계약 블록 경계 — 문서 안 *다른* 표가 우연히 검증을 만족시키는 것을 막는 울타리.
_BLOCK_BEGIN = "<!-- SLO-CONTRACT-BEGIN"
_BLOCK_END = "<!-- SLO-CONTRACT-END"

# 계약 행: | `키` | `값` | ... — 키·값 모두 백틱으로 감싼 형식만 인정한다(느슨한 파싱은
# 표 밖 산문의 숫자를 잘못 집어 거짓 통과를 만든다).
_CONTRACT_ROW = re.compile(
    r"^\|\s*`(?P<key>[a-z0-9_]+)`\s*\|\s*`(?P<value>[0-9]+(?:\.[0-9]+)?)`\s*\|",
    re.MULTILINE,
)

# 문서가 인라인 코드로 적은 경로 토큰(백틱 안). 코드펜스는 사전에 제거하고 뽑는다 —
# PowerShell 예시의 백틱 이스케이프(`n·`t)가 인라인 코드로 오인되는 것을 막기 위함이다.
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_FENCE_BLOCK = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
# 런북 명령 안의 실제 호출 대상(curl 등) — 산문뿐 아니라 *실행되는 URL*도 검증한다.
_LOCAL_URL_PATH = re.compile(r"http://127\.0\.0\.1:\d+(?P<path>/[A-Za-z0-9_\-./{}]*)")
# 검증 대상 경로 접두사 — 문서에 등장하는 파일경로(`docs/...`)·컨테이너 경로(`/tmp/...`)는
# 라우트가 아니므로 제외한다.
_ROUTE_PREFIXES = ("/health", "/status", "/v1/")


def _expected_constants() -> dict[str, float]:
    """계약 키 → 코드 정본 값. env 오염과 무관한 *필드 기본값*을 읽는다(위 docstring)."""
    fields = Settings.model_fields
    return {
        "ops_error_rate_alert_threshold": float(fields["ops_error_rate_alert_threshold"].default),
        "ops_latency_p95_alert_ms": float(fields["ops_latency_p95_alert_ms"].default),
        "ops_metrics_window_size": float(fields["ops_metrics_window_size"].default),
        "l3_sla_gate_ms": float(SLA_GATE_MS),
        # OPS-30: S4 목표·창은 uptime_probe가 정본(프로브가 계산에 쓰는 바로 그 상수).
        "s4_availability_target": float(uptime_probe.S4_AVAILABILITY_TARGET),
        "s4_window_start_kst_hour": float(uptime_probe.S4_WINDOW_START_KST_HOUR),
        "s4_window_end_kst_hour": float(uptime_probe.S4_WINDOW_END_KST_HOUR),
    }


def _extract_contract_block(doc_text: str) -> str | None:
    """[기계 판독] 계약 블록 본문만 잘라낸다. 경계가 없으면 None(=위반 사유)."""
    start = doc_text.find(_BLOCK_BEGIN)
    end = doc_text.find(_BLOCK_END)
    if start == -1 or end == -1 or end <= start:
        return None
    return doc_text[start:end]


def _contract_mismatches(doc_text: str, expected: dict[str, float]) -> list[str]:
    """문서 기재값 ↔ 코드 정본 불일치 목록. 빈 리스트 = 일치(그 외는 전부 실패 사유).

    반환 문자열은 그대로 실패 메시지가 되므로 *무엇을 어디서 어떻게 고쳐야 하는지*를
    담는다 — 무맥락 실패는 다음 사람에게 재조사를 강요한다.
    """
    block = _extract_contract_block(doc_text)
    if block is None:
        return [
            f"계약 블록을 찾지 못했다 — '{_BLOCK_BEGIN}' ~ '{_BLOCK_END}' 주석 경계가 "
            f"{_SLO_DOC.name} §1-5에 있어야 한다(블록이 사라지면 임계 동결이 무력화된다)."
        ]

    documented = {m.group("key"): m.group("value") for m in _CONTRACT_ROW.finditer(block)}
    mismatches: list[str] = []

    for key, code_value in sorted(expected.items()):
        if key not in documented:
            mismatches.append(
                f"[{key}] 계약 블록에 행이 없다 — 코드 정본은 {code_value!r}. "
                f"'| `{key}` | `<값>` | ...' 행을 §1-5 표에 추가하라."
            )
            continue
        doc_value = float(documented[key])
        if doc_value != code_value:
            mismatches.append(
                f"[{key}] 문서={doc_value!r} ≠ 코드={code_value!r} — "
                "코드(config.py Settings 기본값 / l3.router.SLA_GATE_MS)와 "
                f"{_SLO_DOC.name} §1-5를 **함께** 고쳐야 한다(한쪽만 고치면 런북이 거짓말한다)."
            )

    for unknown in sorted(set(documented) - set(expected)):
        mismatches.append(
            f"[{unknown}] 계약 블록에 있으나 코드 정본 매핑이 없다 — 검증되지 않는 "
            "수치를 문서가 주장하고 있다. 이 테스트의 `_expected_constants()`에 매핑을 "
            "추가하거나 행을 삭제하라."
        )
    return mismatches


@lru_cache(maxsize=1)
def _doc_text() -> str:
    return _SLO_DOC.read_text(encoding="utf-8")


# `_app_route_paths`는 원래 이 파일이 자체 정의했다(FastAPI 0.140 `_IncludedRouter` 래퍼 언랩
# 재귀 — 순진하게 `app.routes`의 `path`만 모으면 `/v1/**`이 통째로 누락되는 실측 함정).
# OPS-22가 그 구현을 `ops.declared_unwired_audit.route_paths()`로 승격해 단일 진실 원천으로
# 삼았다 — 여기서는 재구현하지 않고 그 함수를 그대로 재사용한다(재구현 금지).
_app_route_paths = route_paths


def _route_matches(candidate: str, known: frozenset[str]) -> bool:
    """경로 실재 판정 — 정확 일치 또는 템플릿 라우트({param}) 대입 일치.

    문서는 `/v1/auth/demo/callback`처럼 *구체 인스턴스*를 적을 수 있는데 라우트 표에는
    `/v1/auth/{provider}/callback`만 있다. 템플릿을 정규식으로 풀어 그 경우를 인정한다.
    """
    if candidate in known:
        return True
    for template in known:
        if "{" not in template:
            continue
        # re.escape는 {}도 이스케이프하므로 되돌린 뒤 파라미터 자리만 [^/]+로 푼다.
        escaped = re.escape(template).replace(r"\{", "{").replace(r"\}", "}")
        pattern = "^" + re.sub(r"\{[^/}]+\}", "[^/]+", escaped) + "$"
        if re.match(pattern, candidate):
            return True
    return False


def _documented_route_paths(doc_text: str) -> set[str]:
    """문서가 안내하는 경로 토큰 — ①산문 인라인 코드 ②명령 블록의 로컬 URL 두 축.

    와일드카드 표기(`*`·`…`)는 경로 *패턴* 설명이므로 검증에서 제외한다(문서화된 예외).
    """
    prose = _FENCE_BLOCK.sub("", doc_text)  # 코드펜스 제거(PowerShell 백틱 이스케이프 오인 방지)
    found: set[str] = set()
    for token in _INLINE_CODE.findall(prose):
        token = token.strip()
        if token.startswith(_ROUTE_PREFIXES) and not any(ch in token for ch in "*…"):
            found.add(token)
    for match in _LOCAL_URL_PATH.finditer(doc_text):  # 원문 전체(명령 블록 포함)
        found.add(match.group("path"))
    return found


# ──────────────────────────────────────────────────────────────────────────
# ① 임계 동결 — 문서 기재값 == 코드 기본값
# ──────────────────────────────────────────────────────────────────────────
def test_documented_thresholds_match_code_defaults() -> None:
    mismatches = _contract_mismatches(_doc_text(), _expected_constants())
    assert not mismatches, "SLO 문서 ↔ 코드 드리프트:\n- " + "\n- ".join(mismatches)


def test_prose_renderings_derive_from_code_values() -> None:
    """§1의 사람이 읽는 숫자(5% · 5,000ms · 500요청)가 코드값과 어긋나지 않게 동결한다.

    §1-5 계약 블록만 얼면 표는 맞는데 *본문은 옛 숫자*인 문서가 될 수 있다 — 장애 중에
    사람이 읽는 건 대개 본문 쪽이다. 여기서는 코드값으로 표기 문자열을 **생성**해 문서에
    그대로 있는지 본다(문서에서 숫자를 다시 파싱하지 않는다 — 파생 방향이 한쪽이라
    '문서가 스스로를 증명하는' 순환이 없다).

    표기 형식(굵게·천단위 콤마)에 결합돼 있음을 인정한다: 문서를 재포맷하면 이 테스트가
    실패할 수 있고, 그때는 아래 기대 문자열을 새 표기에 맞춰 고치는 것이 정상 절차다.
    """
    expected = _expected_constants()
    doc = _doc_text()
    renderings = {
        "§1-2 S1 즉시 조치선": f"**> {expected['ops_error_rate_alert_threshold'] * 100:g}%**",
        "§1-2 S2 즉시 조치선": f"**> {expected['ops_latency_p95_alert_ms']:,.0f}ms**",
        "§1-3 오류 예산 창": f"최근 {expected['ops_metrics_window_size']:.0f}요청 창",
    }
    missing = [
        f"{where}: '{text}' 가 문서에 없다" for where, text in renderings.items() if text not in doc
    ]
    assert (
        not missing
    ), (
        "코드값에서 파생한 사람용 표기가 문서에 없다 — 본문이 옛 임계를 말하고 있을 수 있다:\n- "
        + "\n- ".join(missing)
    )


def test_contract_block_covers_all_expected_keys() -> None:
    """키 누락이 '검증할 게 없어서 통과'로 둔갑하지 않음을 별도로 못 박는다."""
    block = _extract_contract_block(_doc_text())
    assert block is not None, "계약 블록 경계 주석이 사라졌다(§1-5)"
    documented = {m.group("key") for m in _CONTRACT_ROW.finditer(block)}
    assert documented == set(
        _expected_constants()
    ), f"계약 키 집합 불일치 — 문서={sorted(documented)} / 기대={sorted(_expected_constants())}"


# ──────────────────────────────────────────────────────────────────────────
# ② 경로 실재 — 런북이 안내하는 엔드포인트는 실제로 존재해야 한다
# ──────────────────────────────────────────────────────────────────────────
def test_readiness_paths_exist_in_app_routes() -> None:
    """OPS-04 수용조건이 직접 지목한 두 경로 — 탐지 절차의 뿌리라 따로 단언한다."""
    known = _app_route_paths()
    for required in ("/health/ready", "/health/live"):
        assert required in known, (
            f"{required}가 실제 라우트 표에 없다 — 런북의 탐지 절차가 무효가 된다. "
            "app.py의 엔드포인트 정의를 확인하라."
        )


def test_all_documented_paths_exist_in_app_routes() -> None:
    known = _app_route_paths()
    # 수집기 자체의 침묵 실패 방어: 재귀가 깨지면 기본 10개 남짓만 모인다.
    assert len(known) > 20, (
        f"라우트 수집이 {len(known)}개뿐 — FastAPI include 내부 구조 변경으로 수집기가 "
        "깨졌을 가능성이 크다(`original_router` 재귀 확인)."
    )
    documented = _documented_route_paths(_doc_text())
    assert documented, "문서에서 경로 토큰을 하나도 못 찾았다 — 추출기가 깨졌다(위장 통과 방지)"
    missing = sorted(p for p in documented if not _route_matches(p, known))
    assert (
        not missing
    ), "문서가 존재하지 않는 경로를 안내한다(장애 중 오타 URL을 두드리게 된다):\n- " + "\n- ".join(
        missing
    )


# ──────────────────────────────────────────────────────────────────────────
# ③ 변별력 동결 — 이 테스트가 '실패 상태에서 실제로 실패하는지'를 테스트한다
# ──────────────────────────────────────────────────────────────────────────
def _mutate_contract_value(doc_text: str, key: str, new_value: str) -> str:
    pattern = re.compile(rf"(\|\s*`{re.escape(key)}`\s*\|\s*`)[0-9.]+(`)")
    mutated, count = pattern.subn(rf"\g<1>{new_value}\g<2>", doc_text)
    assert count == 1, f"변조 대상 행을 정확히 1개 찾지 못했다(count={count})"
    return mutated


@pytest.mark.parametrize(
    ("key", "bogus"),
    [
        ("ops_error_rate_alert_threshold", "0.5"),
        ("ops_latency_p95_alert_ms", "9000"),
        ("ops_metrics_window_size", "100"),
        ("l3_sla_gate_ms", "3000"),
    ],
)
def test_mutated_threshold_is_actually_detected(key: str, bogus: str) -> None:
    """임계를 바꾼 문서는 반드시 불일치로 잡힌다 — 통과/실패가 갈리는 검사임을 증명."""
    mutated = _mutate_contract_value(_doc_text(), key, bogus)
    mismatches = _contract_mismatches(mutated, _expected_constants())
    assert any(
        key in m for m in mismatches
    ), f"{key}를 {bogus}로 바꿨는데도 검출되지 않았다 — 이 테스트는 변별력이 없다"


def test_missing_contract_block_is_not_silently_passed() -> None:
    """계약 블록이 통째로 사라진 문서가 '위반 0'으로 통과하면 동결은 위장이다."""
    stripped = _doc_text().replace(_BLOCK_BEGIN, "<!-- 삭제됨")
    mismatches = _contract_mismatches(stripped, _expected_constants())
    assert mismatches, "계약 블록이 없는데도 위반 0으로 통과했다(침묵 실패)"


def test_unknown_path_does_not_match_route_table() -> None:
    """경로 검증의 변별력 — 실재하지 않는 경로는 매칭되지 않아야 한다."""
    known = _app_route_paths()
    assert not _route_matches("/v1/이런경로는없다", known)
    assert _route_matches("/health/ready", known)
    # 템플릿 라우트의 구체 인스턴스는 인정한다(거짓 실패 방지).
    assert _route_matches("/v1/problems/12345", known)


# ──────────────────────────────────────────────────────────────────────────
# ④ OPS-95 — S5(경로별 SLO)의 "측정 가능" 주장 ↔ 코드의 라우트 차원 실재 대조.
# ──────────────────────────────────────────────────────────────────────────
_S5_ROW = re.compile(r"^\| \*\*S5\*\* \|.*$", re.MULTILINE)
_S5_FIELDS = ("p50_latency_ms", "p75_latency_ms", "p95_latency_ms", "error_rate", "count")


def _s5_doc_violations(doc_text: str) -> list[str]:
    """S5 행이 '측정 가능'을 주장하는데 그 수단이 코드에 없거나, 반대로 미측정이라 적었는가."""
    match = _S5_ROW.search(doc_text)
    if match is None:
        return ["S5 행(| **S5** | ...)이 §1-2 표에 없다 — 경로별 SLO 상태가 문서에서 사라졌다."]
    row = match.group(0)
    problems: list[str] = []
    if "미측정" in row or "❌" in row:
        problems.append("S5 행이 미측정으로 적혀 있다 — 라우트 차원이 코드에 있으므로 거짓이다.")
    if "✅" not in row or "측정 가능" not in row:
        problems.append("S5 행에 '✅ 측정 가능' 표기가 없다.")
    if "metrics.routes" not in row:
        problems.append("S5 행이 측정 수단(`metrics.routes`)을 가리키지 않는다.")
    for field in _S5_FIELDS:
        if field in row and field not in RouteLatencyBody.model_fields:
            problems.append(f"S5 행이 `{field}`를 안내하나 응답 스키마(RouteLatencyBody)에 없다.")
    return problems


def _route_dimension_violations(metrics_cls: type[ServiceMetrics]) -> list[str]:
    """계측 클래스가 라우트 차원을 *실제로* 갖는지 행동으로 판정한다(소스 문자열 검사 아님).

    느린 라우트와 빠른 라우트를 기록해 ①두 라우트가 별개 행으로 나오는가 ②각자의 p95가 섞이지
    않았는가 ③미매칭 버킷이 별개로 남는가를 본다. 위반 목록이 비면 차원이 있다.
    """
    metrics = metrics_cls()
    slow, fast, unmatched = "/slow/{x}", "/fast/{x}", "(unmatched)"
    for _ in range(20):
        metrics.record(4000.0, 200, slow)
        metrics.record(20.0, 200, fast)
        metrics.record(5.0, 404, unmatched)
    rows = {row.route: row for row in metrics.snapshot().routes}
    problems: list[str] = []
    for name in (slow, fast, unmatched):
        if name not in rows:
            problems.append(f"라우트 행 '{name}'이 스냅샷에 없다 — 라우트 차원이 없거나 병합됐다.")
    if problems:
        return problems
    if rows[slow].p95_latency_ms != 4000.0 or rows[fast].p95_latency_ms != 20.0:
        problems.append("라우트별 p95가 섞였다 — 두 라우트의 지연이 한 버킷으로 계상됐다.")
    return problems


def test_s5_doc_claim_matches_code_dimension() -> None:
    """문서의 S5 '측정 가능'은 코드에 라우트 차원이 실재할 때만 참이다 — 양쪽 모두 위반 0."""
    assert _s5_doc_violations(_doc_text()) == []
    assert _route_dimension_violations(ServiceMetrics) == []


def test_s5_doc_reverted_to_unmeasured_is_detected() -> None:
    """S5를 '미측정 목표'로 되돌린 문서는 위반으로 잡힌다(문서쪽 변별력)."""
    original = _doc_text()
    mutated = original.replace("✅ **측정 가능**(달성 여부는", "❌ **미측정 목표**(달성 여부는", 1)
    assert mutated != original, "주입이 적용되지 않았다 — 치환 대상 문면이 바뀌었다"
    assert _s5_doc_violations(mutated), "미측정으로 되돌렸는데 검출되지 않았다(변별력 없음)"


def test_s5_missing_row_is_not_silently_passed() -> None:
    """S5 행이 통째로 사라져도 '위반 0'으로 통과하면 안 된다."""
    mutated = _S5_ROW.sub("", _doc_text())
    assert mutated != _doc_text()
    assert _s5_doc_violations(mutated)


def test_mutant_dropping_route_dimension_is_detected() -> None:
    """뮤테이션 A: `route` 인자를 무시하는(=차원 제거) 계측은 RED."""

    class _DropsRoute(ServiceMetrics):
        def record(self, latency_ms: float, status_code: int, route: str | None = None) -> None:
            super().record(latency_ms, status_code)  # route를 버린다

    assert _DropsRoute.record is not ServiceMetrics.record  # 주입이 실제로 적용됐다
    assert _route_dimension_violations(_DropsRoute), "차원 제거를 검출하지 못했다"


def test_mutant_merging_routes_into_one_bucket_is_detected() -> None:
    """뮤테이션 B: 모든 라우트를 한 버킷에 섞는 계측은 RED."""

    class _MergesRoutes(ServiceMetrics):
        def record(self, latency_ms: float, status_code: int, route: str | None = None) -> None:
            super().record(latency_ms, status_code, "(all)")  # 전부 한 키로

    assert _MergesRoutes.record is not ServiceMetrics.record
    assert _route_dimension_violations(_MergesRoutes), "버킷 병합을 검출하지 못했다"
