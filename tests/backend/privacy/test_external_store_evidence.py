"""외부 store 실재 계약 *탐지기 자신*의 변별력 검증(SEC-32).

매니페스트 계약(`_external_store_evidence`)이 무엇을 통과시키고 무엇을 막는지는 그 계약을
쓰는 테스트들이 알아서 보여주지 않는다 — 정상 상태에서는 통과가 곧 초록이고, *모든* 입력을
통과시키는 고장난 탐지기도 똑같이 초록이기 때문이다. 그래서 여기서 **실패해야 하는 입력을
직접 주입해** RED가 나오는지 확인한다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로
선언 금지").

주입 대상은 매니페스트 함수가 아니라 계약 함수의 *인자*다 — 소스를 뮤테이션하지 않고도
"미도입 store를 1건 추가하면 RED"를 재현할 수 있고, 그 재현이 CI에서 상시 돈다.
"""

from __future__ import annotations

import pytest
from _external_store_evidence import (
    KNOWN_DEPLOYED_STORE,
    KNOWN_UNDEPLOYED_STORES,
    assert_detector_is_discriminating,
    assert_manifest_stores_are_deployed,
    evidence_for,
)


class TestDetectorDiscrimination:
    """탐지기가 실재/미도입을 실제로 갈라내는가(양방향)."""

    def test_deployed_store_has_evidence(self) -> None:
        """실배포 store(Redis)는 설정 키와 compose 서비스 양쪽에서 근거가 나온다."""
        evidence = evidence_for(KNOWN_DEPLOYED_STORE)
        assert evidence
        assert any(item.startswith("config.Settings.") for item in evidence)
        assert any("services." in item for item in evidence)

    @pytest.mark.parametrize("store", KNOWN_UNDEPLOYED_STORES)
    def test_undeployed_store_has_no_evidence(self, store: str) -> None:
        """미도입 store(ClickHouse·S3)는 근거 0건 — 슬라이스 라벨 'S3-01' 같은 *주석*에 속지 않는다."""
        assert evidence_for(store) == ()

    def test_self_check_passes_in_current_repo(self) -> None:
        """탐지기 자기검증이 현행 저장소에서 통과한다(스캔 0건·전건 통과 위장 방어)."""
        assert_detector_is_discriminating()


class TestManifestContractRejects:
    """계약이 *실제로 막는지* — 실패해야 하는 입력을 주입해 RED를 확인한다."""

    def test_undeployed_store_injection_is_rejected(self) -> None:
        """미도입 store를 매니페스트에 1건 추가하면 계약이 거부한다(변별력 요구의 본체)."""
        with pytest.raises(AssertionError) as excinfo:
            assert_manifest_stores_are_deployed(
                [KNOWN_DEPLOYED_STORE, "clickhouse"], source="주입 테스트"
            )
        assert "clickhouse" in str(excinfo.value)
        assert "주입 테스트" in str(excinfo.value)  # 어느 매니페스트가 거짓인지 지목한다

    def test_unknown_store_name_is_rejected(self) -> None:
        """표기를 바꾼 가상의 store명도 근거가 없으면 거부된다(금지 문자열 열거가 아니므로)."""
        with pytest.raises(AssertionError):
            assert_manifest_stores_are_deployed(["analytics_warehouse"], source="주입 테스트")

    def test_empty_manifest_is_rejected(self) -> None:
        """빈 매니페스트도 거부 — '외부 반출처 없음' 주장은 스캔 0건과 구별되지 않는다."""
        with pytest.raises(AssertionError):
            assert_manifest_stores_are_deployed([], source="주입 테스트")

    def test_real_manifest_passes(self) -> None:
        """현행 매니페스트(Redis·Langfuse)는 통과한다 — 계약이 참인 것까지 막지는 않는다."""
        assert_manifest_stores_are_deployed([KNOWN_DEPLOYED_STORE, "langfuse"], source="정상 표본")
