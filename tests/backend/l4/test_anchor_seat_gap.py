"""MISC-21 — 앵커 좌석 갭 측정(`anchor_seat_gap`) 단위테스트 + 실 코퍼스 회귀.

acceptance ① 재현: 커밋된 실 코퍼스(앵커 레지스트리·misconceptions_v1·crosslinks.json)로
"A1=0·A2=0·A3=0·A4=3·A5=0·A6=2 좌석(M-id는 A1=4·A2=2·A3=4·A4=8·A5=2·A6=8)"을 그대로 재현한다.

변별력(핵심 요구): `TestSeatVsNoSeatDiscrimination`은 좌석이 있는 상태와 없는 상태를 합성
데이터로 직접 만들어 `compute_seat_gap`이 실제로 다른 값을 내는지 확인한다 — 항상 같은 값을
내는 위장 검사가 아님(CLAUDE.md "변별력 없는 검증 스텝 금지"). `TestRealCorpusMutation`은 실
crosslinks.json에서 좌석 있는 앵커(A4)의 행을 제거·복원해 같은 변별력을 실 파일 경로로도 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l1.standards.anchor_registry import (
    SCOPE_DECEMBER_2026,
    default_registry_path,
    load_anchor_registry,
)
from whymath_backend.l4.misconception.anchor_seat_gap import (
    DEFAULT_CROSSLINKS_PATH,
    DEFAULT_MISCONCEPTIONS_PATH,
    AnchorSeatGapError,
    compute_seat_gap,
    load_and_compute,
    main,
)

_ROOT = Path(__file__).resolve().parents[3]
_MIS_PATH = _ROOT / DEFAULT_MISCONCEPTIONS_PATH
_XLINK_PATH = _ROOT / DEFAULT_CROSSLINKS_PATH


# ── acceptance ① — 실 코퍼스 재현 ───────────────────────────────────────────


@pytest.fixture(scope="module")
def real_results() -> dict[str, object]:
    registry = load_anchor_registry(default_registry_path())
    anchors = registry.in_scope(SCOPE_DECEMBER_2026)
    misconceptions = json.loads(_MIS_PATH.read_text(encoding="utf-8"))["misconceptions"]
    crosslinks = json.loads(_XLINK_PATH.read_text(encoding="utf-8"))["crosslinks"]
    results = compute_seat_gap(anchors, misconceptions, crosslinks)
    return {r.anchor_id: r for r in results}


class TestRealCorpusReproducesMisc07Measurement:
    """MISC-07 착수 시점 실측(main 기준) 재현 — MISC-21 acceptance ①."""

    @pytest.mark.parametrize(
        ("anchor_id", "expected_mis_id_count", "expected_seat_count"),
        [
            ("A1", 4, 0),
            ("A2", 2, 0),
            ("A3", 4, 0),
            ("A4", 8, 3),
            ("A5", 2, 0),
            ("A6", 8, 2),
        ],
    )
    def test_anchor_counts(
        self,
        real_results: dict[str, object],
        anchor_id: str,
        expected_mis_id_count: int,
        expected_seat_count: int,
    ) -> None:
        result = real_results[anchor_id]
        assert result.mis_id_count == expected_mis_id_count
        assert result.seat_count == expected_seat_count

    def test_six_december_anchors_present(self, real_results: dict[str, object]) -> None:
        assert set(real_results) == {"A1", "A2", "A3", "A4", "A5", "A6"}

    def test_a4_seated_kebabs_are_the_expected_three(self, real_results: dict[str, object]) -> None:
        result = real_results["A4"]
        assert result.seated_kebab_ids == (
            "factor-sign-flip",
            "opposite-root-selected",
            "root-loss-by-dividing",
        )

    def test_a6_seated_kebabs_are_the_expected_two(self, real_results: dict[str, object]) -> None:
        result = real_results["A6"]
        assert result.seated_kebab_ids == (
            "extremum-max-min-confused",
            "extremum-value-vs-point-confused",
        )

    def test_zero_seat_anchors_still_have_unseated_mis_ids_listed(
        self, real_results: dict[str, object]
    ) -> None:
        # 좌석 0 = "오개념이 없다"가 아니라 "M-id는 있는데 미연결"임을 데이터로 증명.
        for anchor_id in ("A1", "A2", "A3", "A5"):
            result = real_results[anchor_id]
            assert result.seat_count == 0
            assert result.mis_id_count > 0
            assert set(result.unseated_mis_ids) == set(result.mis_ids)


# ── 변별력 — 합성 데이터로 좌석 있음/없음을 실제로 구별하는가 ────────────────


class _FakeAnchor:
    def __init__(self, id: str, title: str, scope: str, codes: tuple[str, ...]) -> None:
        self.id = id
        self.title = title
        self.scope = scope
        self.codes = codes


class TestSeatVsNoSeatDiscrimination:
    """이 검사 자체가 변별력을 갖는가 — 항상 seat_count=0을 내는 위장 검사가 아님을 증명."""

    def test_no_crosslink_row_yields_zero_seats(self) -> None:
        anchor = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        (result,) = compute_seat_gap([anchor], misconceptions, crosslinks=[])
        assert result.mis_id_count == 1
        assert result.seat_count == 0
        assert result.unseated_mis_ids == ("M9001",)

    def test_adding_a_matching_crosslink_flips_seat_count_to_nonzero(self) -> None:
        # 위 상태와 입력 M-id는 동일 — crosslinks 행 1건만 추가했을 때 결과가 실제로 바뀌는가.
        anchor = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [{"kebab_id": "fake-kebab", "mis_id": "M9001"}]
        (result,) = compute_seat_gap([anchor], misconceptions, crosslinks)
        assert result.seat_count == 1
        assert result.seated_kebab_ids == ("fake-kebab",)
        assert result.unseated_mis_ids == ()

    def test_crosslink_for_unrelated_mis_id_does_not_leak_a_seat(self) -> None:
        # 다른 M-id를 겨눈 crosslink는 이 앵커의 좌석으로 잘못 세면 안 된다(오탐 방지).
        anchor = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [{"kebab_id": "fake-kebab", "mis_id": "M9999"}]
        (result,) = compute_seat_gap([anchor], misconceptions, crosslinks)
        assert result.seat_count == 0

    def test_removing_the_crosslink_reverts_to_zero(self) -> None:
        anchor = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        seeded = [{"kebab_id": "fake-kebab", "mis_id": "M9001"}]
        with_seat = compute_seat_gap([anchor], misconceptions, seeded)[0]
        without_seat = compute_seat_gap([anchor], misconceptions, [])[0]
        assert with_seat.seat_count == 1
        assert without_seat.seat_count == 0

    def test_two_kebabs_linked_to_same_mis_id_count_as_two_seats(self) -> None:
        anchor = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [
            {"kebab_id": "fake-kebab-a", "mis_id": "M9001"},
            {"kebab_id": "fake-kebab-b", "mis_id": "M9001"},
        ]
        (result,) = compute_seat_gap([anchor], misconceptions, crosslinks)
        assert result.seat_count == 2


class TestMalformedRowsRejected:
    """필수 필드 누락 행은 건너뛰지 않고 던진다(PR #1068 Codex P2 — 침묵 실패 금지).

    조용히 건너뛰면 "좌석이 진짜 0"과 "스키마 드리프트로 못 읽었다"가 같은 출력(0건)이 되어
    부분 생성 코퍼스가 진짜 좌석 갭인 척한다.
    """

    _ANCHOR = _FakeAnchor("AX", "합성 앵커", "december_2026", ("[TEST-01]",))

    def test_misconception_row_missing_standard_code_raises(self) -> None:
        misconceptions = [{"mis_id": "M9001"}]  # standard_code 누락
        with pytest.raises(AnchorSeatGapError):
            compute_seat_gap([self._ANCHOR], misconceptions, crosslinks=[])

    def test_misconception_row_missing_mis_id_raises(self) -> None:
        misconceptions = [{"standard_code": "[TEST-01]"}]  # mis_id 누락
        with pytest.raises(AnchorSeatGapError):
            compute_seat_gap([self._ANCHOR], misconceptions, crosslinks=[])

    def test_crosslink_row_missing_mis_id_raises(self) -> None:
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [{"kebab_id": "fake-kebab"}]  # mis_id 누락
        with pytest.raises(AnchorSeatGapError):
            compute_seat_gap([self._ANCHOR], misconceptions, crosslinks)

    def test_crosslink_row_missing_kebab_id_raises(self) -> None:
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [{"mis_id": "M9001"}]  # kebab_id 누락
        with pytest.raises(AnchorSeatGapError):
            compute_seat_gap([self._ANCHOR], misconceptions, crosslinks)

    def test_well_formed_rows_still_pass(self) -> None:
        """회귀 가드 — 반박 강화가 정상 입력까지 거부하지 않는지."""
        misconceptions = [{"standard_code": "[TEST-01]", "mis_id": "M9001"}]
        crosslinks = [{"kebab_id": "fake-kebab", "mis_id": "M9001"}]
        (result,) = compute_seat_gap([self._ANCHOR], misconceptions, crosslinks)
        assert result.seat_count == 1


class TestRealCorpusMutation:
    """실 crosslinks.json 경로로도 같은 변별력을 확인 — 파일 I/O 경로 자체를 검증."""

    def test_removing_a4_rows_from_real_crosslinks_drops_seat_to_zero(self) -> None:
        registry = load_anchor_registry(default_registry_path())
        anchors = [a for a in registry.in_scope(SCOPE_DECEMBER_2026) if a.id == "A4"]
        misconceptions = json.loads(_MIS_PATH.read_text(encoding="utf-8"))["misconceptions"]
        crosslinks = json.loads(_XLINK_PATH.read_text(encoding="utf-8"))["crosslinks"]

        baseline = compute_seat_gap(anchors, misconceptions, crosslinks)[0]
        assert baseline.seat_count == 3  # 뮤테이션 전 — 실 코퍼스 기준값

        mutated = [row for row in crosslinks if row["mis_id"] not in {"M0573", "M0862", "M0863"}]
        mutated_result = compute_seat_gap(anchors, misconceptions, mutated)[0]
        assert mutated_result.seat_count == 0  # 뮤테이션 후 — RED가 실제로 남

        restored = compute_seat_gap(anchors, misconceptions, crosslinks)[0]
        assert restored.seat_count == 3  # 원복 후 — 원래 값으로 돌아옴(하네스 자체의 정합)


# ── 로더·CLI ────────────────────────────────────────────────────────────


class TestLoadAndCompute:
    def test_matches_pure_function_on_real_files(self, real_results: dict[str, object]) -> None:
        loaded = {r.anchor_id: r for r in load_and_compute()}
        assert loaded.keys() == real_results.keys()
        for anchor_id, result in real_results.items():
            assert loaded[anchor_id].seat_count == result.seat_count
            assert loaded[anchor_id].mis_id_count == result.mis_id_count

    def test_missing_misconceptions_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AnchorSeatGapError):
            load_and_compute(
                misconceptions_path=tmp_path / "nope.json",
                crosslinks_path=_XLINK_PATH,
            )

    def test_malformed_top_key_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"wrong_key": []}), encoding="utf-8")
        with pytest.raises(AnchorSeatGapError):
            load_and_compute(misconceptions_path=bad, crosslinks_path=_XLINK_PATH)


class TestCli:
    def test_json_mode_exit_zero_and_lists_six_anchors(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--json"])
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert {row["anchor_id"] for row in out} == {"A1", "A2", "A3", "A4", "A5", "A6"}
        by_id = {row["anchor_id"]: row for row in out}
        assert by_id["A1"]["seat_count"] == 0
        assert by_id["A4"]["seat_count"] == 3

    def test_text_mode_exit_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main([])
        assert code == 0
        out = capsys.readouterr().out
        assert "A4" in out and "좌석 3" in out

    def test_bad_registry_path_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--registry", str(tmp_path / "nope.yaml")])
        assert code == 1
        assert "적재 실패" in capsys.readouterr().err
