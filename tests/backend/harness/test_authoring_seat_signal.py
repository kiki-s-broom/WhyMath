"""EOS-111 — 저작 회차 요약이 '어느 좌석이 실제로 돌았는가'를 말하는가.

**상환하는 사고**(2026-09-18 Phaiakes9 라이브 1회차): OpenRouter 좌석으로 돌린 저작 회차가
`EXIT=0`·5/5 저장으로 끝났는데 **그 좌석이 서빙했는지 요약만으로 판정할 수 없었다**.
`prompt_cache`의 `calls_with_cache_telemetry: 0`이 "이 provider가 캐시 필드를 노출하지
않는다"와 "LOCAL 경로만 돌았다" 양쪽에서 같은 값이라 변별력이 0이었고, genlog 사이드카를
따로 열어야 알 수 있었다.

**판정의 범위**(ARCH-58): `model_name`은 *설정이 지목한* 모델이지 *응답이 온* 모델이
아니다. 그래서 이 신호는 "라우팅이 클라우드로 갔고 그 좌석이 선택과 같은가"까지 답하고,
provider 측 대체·폴백은 보지 못한다 — 그 축은 `EOS-112`가 소유한다.

hermetic: 순수 함수만 — 네트워크·키·DB·파일 I/O 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whymath_backend.harness.anchor_round_ledger import (
    SEAT_STATES,
    SeatTally,
    seat_operating_rates,
)

_OR_MID = "deepseek/deepseek-v4.1-flash"
_OR_HIGH = "deepseek/deepseek-v4-pro"
_LOCAL = "qwen2.5:7b"
_PINS = (_OR_MID, _OR_HIGH)

# 저장소 루트 — `tests/backend/harness/<file>` 기준 3단계 위다. 아래 집행 지점
# 테스트들이 소스를 읽으므로, 이 값이 틀리면 **배선 부재가 아니라 경로 오류로**
# 실패해 원인을 오독하게 된다(초안이 정확히 그랬다 — parents[2]는 tests/였다).
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _tally(*rows: tuple[str | None, bool | None, float | None]) -> SeatTally:
    tally = SeatTally()
    for model_name, success, cost_usd in rows:
        tally = tally.observe(model_name=model_name, success=success, cost_usd=cost_usd)
    return tally


# ===========================================================================
# ④ⓐ 이번 사고 그 자체 — 셀렉터는 openrouter인데 LOCAL만 돌았다
# ===========================================================================


def test_selector_openrouter_but_only_local_ran_is_visible() -> None:
    """요약이 '선택 좌석에서 0건'이라고 **말해야** 한다 — 이 신호가 존재하는 이유.

    종전에는 이 상태와 정상 회차가 요약에서 구별되지 않았다(둘 다 `EXIT=0`·저장 성공).
    """
    rates = seat_operating_rates(
        _tally((_LOCAL, True, 0.0), (_LOCAL, True, 0.0)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["state"] == "none_on_selected_seat"
    assert rates["calls_on_selected_seat"] == 0
    assert rates["calls_off_selected_seat"] == 2
    assert rates["observed_models"] == {_LOCAL: 2}
    assert rates["selected_seat"] == "openrouter"
    assert rates["measured"] is True  # 측정은 됐다 — 좌석이 안 돈 것이지 미측정이 아니다


def test_selected_seat_actually_ran_is_the_control() -> None:
    """대조군 — 정상 회차는 `all_on_selected_seat`다.

    이 단언이 없으면 "무조건 none_on_selected_seat을 낸다"는 잘못된 구현도 위 테스트를
    통과한다(과잉 검출).
    """
    rates = seat_operating_rates(
        _tally((_OR_MID, True, 0.001), (_OR_MID, True, 0.001)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["state"] == "all_on_selected_seat"
    assert rates["calls_on_selected_seat"] == 2
    assert rates["calls_off_selected_seat"] == 0


# ===========================================================================
# ④ⓑ 혼재 회차 — 한쪽으로 접지 않는다
# ===========================================================================


def test_mixed_cloud_and_local_round_is_reported_as_mixed() -> None:
    """클라우드·로컬 혼재를 `all_*`이나 `none_*` 어느 쪽으로도 접지 않는다."""
    rates = seat_operating_rates(
        _tally((_OR_MID, True, 0.001), (_LOCAL, True, 0.0), (_OR_HIGH, True, 0.004)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["state"] == "mixed"
    assert rates["calls_on_selected_seat"] == 2  # mid + high 둘 다 좌석 핀이다
    assert rates["calls_off_selected_seat"] == 1


# ===========================================================================
# ④ⓒ 미측정과 0의 구분 — 이 집계의 급소
# ===========================================================================


def test_rows_without_model_name_are_unmeasured_not_off_seat() -> None:
    """`model_name` 미기록 행을 '좌석 밖'으로 계상하지 않는다(미측정 ≠ 0).

    접었다면 기록이 빠진 회차가 "좌석이 안 돌았다"로 위장된다.
    """
    rates = seat_operating_rates(
        _tally((None, True, None), (None, None, None)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["state"] == "not_measured"
    assert rates["calls_total"] == 2  # 관측 규모는 남는다
    assert rates["calls_with_model_name"] == 0
    assert rates["calls_off_selected_seat"] == 0, "미기록이 '좌석 밖'으로 계상됐다"
    assert rates["unmeasured_reason"] is not None
    assert "미측정" in rates["unmeasured_reason"]


def test_partial_model_name_rows_do_not_pollute_the_denominator() -> None:
    """혼재 중 미기록 행은 분모에서 빠진다 — 있는 행만으로 판정한다."""
    rates = seat_operating_rates(
        _tally((_OR_MID, True, 0.001), (None, True, None)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["state"] == "all_on_selected_seat"  # 측정된 1건은 전부 좌석 위
    assert rates["calls_total"] == 2
    assert rates["calls_with_model_name"] == 1
    assert rates["calls_off_selected_seat"] == 0


# ===========================================================================
# 부수 축 — 성공/실패·비용의 미상 구분
# ===========================================================================


def test_success_none_counts_as_neither_succeeded_nor_failed() -> None:
    """`success`가 None인 행은 성공도 실패도 아니다 — 모름을 실패로 접지 않는다."""
    tally = _tally((_OR_MID, True, None), (_OR_MID, False, None), (_OR_MID, None, None))
    assert tally.succeeded == 1
    assert tally.failed == 1
    assert tally.calls_total == 3


def test_cost_total_is_none_when_no_row_carried_cost() -> None:
    """비용을 실은 행이 0건이면 합을 `0.0`(0원 확정)으로 내지 않고 None(미상)으로 낸다."""
    rates = seat_operating_rates(
        _tally((_OR_MID, True, None)), selected_seat="openrouter", seat_model_pins=_PINS
    )
    assert rates["cost_usd_total"] is None
    assert rates["calls_with_cost"] == 0
    assert rates["cost_note"] == "단가 곱셈·청구서 미대조"


def test_cost_total_sums_only_rows_that_carried_cost() -> None:
    """대조군 — 실은 행이 있으면 합이 나온다(위 테스트가 '항상 None'을 통과시키지 않게)."""
    rates = seat_operating_rates(
        _tally((_OR_MID, True, 0.001), (_LOCAL, True, None)),
        selected_seat="openrouter",
        seat_model_pins=_PINS,
    )
    assert rates["cost_usd_total"] == pytest.approx(0.001)
    assert rates["calls_with_cost"] == 1


# ===========================================================================
# 계약 — 상태 어휘와 선언/관측 경계 표기
# ===========================================================================


def test_every_reachable_state_is_in_the_vocabulary() -> None:
    """네 상태가 전부 실제로 도달 가능하고 어휘에 등재돼 있다(죽은 어휘 방지)."""
    cases = {
        "not_measured": _tally((None, None, None)),
        "all_on_selected_seat": _tally((_OR_MID, True, None)),
        "none_on_selected_seat": _tally((_LOCAL, True, None)),
        "mixed": _tally((_OR_MID, True, None), (_LOCAL, True, None)),
    }
    reached = {
        seat_operating_rates(t, selected_seat="openrouter", seat_model_pins=_PINS)["state"]
        for t in cases.values()
    }
    assert reached == SEAT_STATES, f"도달한 상태 {sorted(reached)} ≠ 어휘 {sorted(SEAT_STATES)}"


def test_report_states_that_model_name_is_declared_not_observed() -> None:
    """요약이 **선언값임을 스스로 밝힌다** — 읽는 사람이 이 신호를 과신하지 않게.

    이 문구가 사라지면 다음 사람이 "OpenRouter가 답했다"로 읽는데, 이 `state`가 아는
    것은 "설정이 OpenRouter를 지목했고 라우팅이 클라우드로 갔다"까지다.

    2026-09-19 갱신: `EOS-112`가 착지해 관측 축이 **실재한다** — 응답에서 읽은 값은
    같은 요약의 `observation` 블록에 따로 실린다. 두 값을 한 필드로 합치지 않는 이유는
    provider가 모델 식별자를 안 돌려주는 회차에서 '관측 실패'가 '선언값과 일치'로
    위장되기 때문이다. 그래서 이 문구는 여전히 필요하다(축이 생겼다고 없앨 것이 아니라,
    어느 축이 무엇을 아는지를 계속 말해야 한다).
    """
    rates = seat_operating_rates(
        _tally((_OR_MID, True, None)), selected_seat="openrouter", seat_model_pins=_PINS
    )
    assert "EOS-112" in rates["declared_not_observed"]
    assert "선언값" in rates["declared_not_observed"]


def test_unknown_seat_with_no_pins_reports_off_seat_not_crash() -> None:
    """설정 판독 실패 경로(`selected_seat='unknown'`·핀 없음)도 판정을 낸다.

    배치가 이 경로에서 예외를 던지면 회차 전체가 죽는다 — 관측 실패가 작업 실패가 되면 안 된다.
    """
    rates = seat_operating_rates(
        _tally((_LOCAL, True, None)), selected_seat="unknown", seat_model_pins=()
    )
    assert rates["state"] == "none_on_selected_seat"
    assert rates["selected_seat"] == "unknown"
    assert rates["seat_model_pins"] == []


# ===========================================================================
# 집행 지점(①과 별항 — CLAUDE.md 「정본화를 집행으로 착각한 완료 선언 금지」)
#
# 위 테스트들은 *집계기*를 검증한다. 그것이 저작 배치의 요약에 **실제로 실리는가**는
# 다른 질문이고, 실리지 않으면 이 태스크는 아무것도 바꾸지 않은 것이다 — 라이브 회차에서
# 요약을 열었을 때 여전히 좌석을 알 수 없다.
# ===========================================================================


def test_batch_sink_feeds_the_seat_tally() -> None:
    """저작 배치의 genlog 싱크가 좌석 원장을 실제로 먹인다 — AST로 구성된 결과를 본다."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src/backend/whymath_backend/harness/problem_corpus_accumulate.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    sink = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_genlog_sink"
        ),
        None,
    )
    assert sink is not None, "_genlog_sink가 사라졌다 — 이 가드가 볼 자리가 없어졌다"

    observe_targets = {
        node.func.value.id
        for node in ast.walk(sink)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "observe"
        and isinstance(node.func.value, ast.Name)
    }
    assert "seat_tally" in observe_targets, (
        "싱크가 seat_tally.observe(...)를 부르지 않는다 — 집계기는 있는데 아무 행도 "
        f"들어가지 않는다(관측된 observe 대상: {sorted(observe_targets)})."
    )
    assert "cache_tally" in observe_targets, (
        "cache_tally.observe가 사라졌다 — 이 가드의 대조군이 무너졌으므로 위 단언도 "
        "무력화됐을 수 있다(패턴 자체를 재확인하라)."
    )


def test_batch_payload_carries_the_seat_signal() -> None:
    """요약 payload에 `cloud_seat` 키가 실린다 — 캐시 신호와 같은 취급."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src/backend/whymath_backend/harness/problem_corpus_accumulate.py"
    ).read_text(encoding="utf-8")
    assert (
        'payload["cloud_seat"] = seat_operating_rates(' in source
    ), "요약에 좌석 신호가 실리지 않는다 — 집계기만 있고 집행 지점이 없다."
    assert (
        'payload["prompt_cache"] = prompt_cache_rates(' in source
    ), "대조군(prompt_cache 배선)이 사라졌다 — 이 가드의 패턴 전제가 깨졌다."


def test_selector_name_helper_is_actually_called_in_production() -> None:
    """`cloud_provider_name()`이 프로덕션에서 실제로 불린다(acceptance ③ 선언≠배선 해소).

    ARCH-57이 이 함수를 신설했으나 호출처가 `__all__`과 테스트뿐이었다. 이 태스크가
    그것을 닫는다 — 다시 호출처가 0건이 되면 red다.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "cloud_provider_name(",
            str(root / "src/backend/whymath_backend"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    callers = [
        line
        for line in result.stdout.splitlines()
        if "def cloud_provider_name(" not in line and '"cloud_provider_name"' not in line
    ]
    assert callers, (
        "cloud_provider_name()의 프로덕션 호출처가 0건이다 — 선언만 남은 상태로 돌아갔다. "
        "부르거나, 부르지 않기로 판정하고 제거하라(선언만 남겨 두지 않는다)."
    )
    assert sys.version_info >= (3, 12)  # 실행 환경 전제 명시(런너 차이로 인한 오독 방지)
