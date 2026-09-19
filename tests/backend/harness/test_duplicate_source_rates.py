"""중복 출처 교차표 + 구분 장치의 **작동한 비율**(EOS-121 선결조건 B·순수 함수).

「작동한 비율」 원칙(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지")의 적용이다: 출처 구분
장치를 붙였으면 그것이 *실제로 구분한 비율*이 회차 요약에 보여야 한다. 중복 4건이 전부
미판정인 회차와 4건 전부 코퍼스 중복인 회차는 조치가 정반대인데, 종전에는 둘 다
`rejected_duplicate: 4`로 같은 화면이었다.

이 파일이 겨냥하는 뮤테이션(각 테스트가 그 절의 반례를 픽스처로 들고 있다):
  - 중복 0건을 `0%`로 적는다 → `test_no_duplicates_is_unmeasured_not_zero`
  - 미판정을 분모에서 빼거나 키에서 지운다 → `test_unresolved_origin_is_counted_not_dropped`
  - 어휘 밖 값을 조용히 버린다 → `test_unknown_vocabulary_is_confessed_not_dropped`
  - 두 비율을 한 숫자로 접는다 → `test_detector_known_but_origin_unknown_splits_two_rates`
  - 관측 0인 조합의 키를 뺀다 → `test_counts_cover_full_vocabulary`
  - 전건을 한쪽으로 계상한다(과잉 구현) → `test_full_cross_tab_counts`(성공 방향 대조군)
"""

from __future__ import annotations

from whymath_backend.harness.anchor_round_ledger import (
    DUPLICATE_DETECTORS,
    DUPLICATE_ORIGINS,
    duplicate_source_rates,
)


class TestVocabulary:
    def test_vocabulary_is_derived_from_orchestrator_literals(self) -> None:
        """어휘는 오케스트레이터 Literal 파생 — 여기 손으로 베껴 두면 축이 늘 때 조용히 빠진다."""
        assert set(DUPLICATE_DETECTORS) == {"structural_signature", "embedding_near"}
        assert set(DUPLICATE_ORIGINS) == {"round", "corpus", "mixed"}

    def test_counts_cover_full_vocabulary(self) -> None:
        """관측 0인 조합도 **키로 명시**된다 — 키 부재와 0건은 다르다."""
        result = duplicate_source_rates([("structural_signature", "round")])
        expected_keys = {
            f"{detector}/{origin}"
            for detector in (*DUPLICATE_DETECTORS, "unclassified")
            for origin in (*DUPLICATE_ORIGINS, "unknown")
        }
        assert set(result["counts"]) == expected_keys
        assert result["counts"]["embedding_near/mixed"] == 0  # 0건이 0으로 보인다


class TestMeasurability:
    def test_no_duplicates_is_unmeasured_not_zero(self) -> None:
        """중복 0건 = **잴 것이 없었다**(미측정 ≠ 0).

        **이 절의 반례**: 비율을 0.0으로 채우는 구현은 "구분 0% 달성"이라는 거짓 경보를 내고,
        중복이 아예 없던 건강한 회차가 장치 고장으로 읽힌다.
        """
        result = duplicate_source_rates([])
        assert result["duplicates_total"] == 0
        assert result["measured"] is False
        assert result["classified_rate"] is None
        assert result["origin_resolved_rate"] is None
        assert result["unmeasured_reason"] is not None
        assert sum(result["counts"].values()) == 0

    def test_all_classified_gives_full_rate(self) -> None:
        """**성공 방향 대조군** — 전건 판정되면 두 비율이 1.0이다.

        이것이 없으면 "항상 미판정으로 계상"하는 구현이 위 미측정 테스트만으로는 통과한다.
        """
        result = duplicate_source_rates(
            [("structural_signature", "round"), ("embedding_near", "corpus")]
        )
        assert result["measured"] is True
        assert result["classified"] == 2
        assert result["classified_rate"] == 1.0
        assert result["origin_resolved"] == 2
        assert result["origin_resolved_rate"] == 1.0


class TestCrossTab:
    def test_full_cross_tab_counts(self) -> None:
        """네 조합이 **각각 제 칸에** 들어간다 — 한쪽으로 몰아 계상하는 구현을 배제한다."""
        result = duplicate_source_rates(
            [
                ("structural_signature", "round"),
                ("structural_signature", "round"),
                ("structural_signature", "corpus"),
                ("embedding_near", "corpus"),
                ("embedding_near", "mixed"),
            ]
        )
        assert result["counts"]["structural_signature/round"] == 2
        assert result["counts"]["structural_signature/corpus"] == 1
        assert result["counts"]["embedding_near/corpus"] == 1
        assert result["counts"]["embedding_near/mixed"] == 1
        assert result["by_detector"] == {
            "structural_signature": 3,
            "embedding_near": 2,
            "unclassified": 0,
        }
        assert result["by_origin"] == {"round": 2, "corpus": 2, "mixed": 1, "unknown": 0}
        # 합계 보존 — 어느 축으로 세도 총건수와 같아야 한다(조용한 누락 검출).
        assert sum(result["counts"].values()) == 5
        assert sum(result["by_detector"].values()) == 5
        assert sum(result["by_origin"].values()) == 5

    def test_unresolved_origin_is_counted_not_dropped(self) -> None:
        """출처 미판정은 `unknown` 칸에 **남는다** — 분모에서 빠지지 않는다.

        **이 절의 반례**: 미판정 건을 건너뛰는 구현은 `duplicates_total`과 `counts` 합이
        어긋나는데, 그 어긋남은 아무 에러도 내지 않고 비율만 조용히 부풀린다.
        """
        result = duplicate_source_rates(
            [("structural_signature", None), ("structural_signature", "corpus")]
        )
        assert result["duplicates_total"] == 2
        assert result["counts"]["structural_signature/unknown"] == 1
        assert result["by_origin"]["unknown"] == 1
        assert sum(result["counts"].values()) == 2

    def test_detector_known_but_origin_unknown_splits_two_rates(self) -> None:
        """검출기 비율과 출처 비율은 **따로** 나온다.

        검출기는 orchestrator가 항상 채우고 출처만 좌석 주입에 달려 있어, 한 숫자로 접으면
        '어느 쪽이 빠졌는지' 알 수 없다 — 그러면 "좌석을 안 줬다"가 "검출기가 고장났다"로
        읽힌다(조치가 정반대다).
        """
        result = duplicate_source_rates([("structural_signature", None), ("embedding_near", None)])
        assert result["classified_rate"] == 1.0  # 검출기는 전건 알고 있다
        assert result["origin_resolved_rate"] == 0.0  # 출처는 전건 모른다
        assert result["by_origin"]["unknown"] == 2

    def test_fully_unclassified_is_visible(self) -> None:
        """검출기조차 없는 건(구판 경로·미상)도 `unclassified` 칸에 남는다."""
        result = duplicate_source_rates([(None, None), (None, None)])
        assert result["classified"] == 0
        assert result["classified_rate"] == 0.0
        assert result["counts"]["unclassified/unknown"] == 2

    def test_unknown_vocabulary_is_confessed_not_dropped(self) -> None:
        """어휘 밖 값은 **버리지 않고 자백**한다 — 어휘 드리프트가 리포트에 보여야 한다.

        **이 절의 반례**: 어휘 밖을 조용히 버리면 합계가 줄고, 축이 추가된 날 통계가 소리 없이
        틀리기 시작한다(오케스트레이터 파생 어휘가 있어도 구판 JSONL 재집계에서는 날 수 있다).
        """
        result = duplicate_source_rates([("brand_new_detector", "brand_new_origin")])
        assert result["unknown_detectors"] == {"brand_new_detector": 1}
        assert result["unknown_origins"] == {"brand_new_origin": 1}
        assert result["counts"]["unclassified/unknown"] == 1
        assert sum(result["counts"].values()) == 1  # 합계 보존
        assert result["classified"] == 0  # 어휘 밖은 '판정됨'으로 치지 않는다
