"""wh1_shadow_logconfig.json 회귀 동결 — ASCII 불변·cp949 안전·dictConfig 로드·캡처.

2026-07-17 라이브 사고의 재발 방지: uvicorn은 `--log-config` JSON을 **OS 로케일 인코딩**
(한국어 Windows=cp949)으로 읽는다 — 파일에 비ASCII 바이트가 하나라도 있으면 Kiki 머신에서
`UnicodeDecodeError`로 서버 기동 자체가 실패한다(실측). 이 테스트가 ASCII 불변을 동결해
한국어 주석이 다시 들어가는 회귀를 CI에서 잡는다.
"""

from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGCONFIG = _REPO_ROOT / "scripts" / "demo" / "wh1_shadow_logconfig.json"

# 수확기가 파싱 대상으로 삼는 로거 — wh1_shadow.record_logger와 동일해야 캡처가 성립.
_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"


def test_logconfig_is_ascii_only() -> None:
    """비ASCII 바이트 0 — cp949(한국어 Windows 로케일)로도 안전하게 디코드된다."""
    data = _LOGCONFIG.read_bytes()
    data.decode("ascii")  # 비ASCII가 있으면 UnicodeDecodeError로 실패
    data.decode("cp949")  # 사고 당시 실패 지점의 직접 재현 검사


def test_logconfig_captures_record_logger(tmp_path: Path) -> None:
    """dictConfig 로드 + record 로거 라인이 순수 메시지로 파일 캡처된다(e2e)."""
    config = json.loads(_LOGCONFIG.read_text(encoding="ascii"))
    out = tmp_path / "records.log"
    # PED-48: 설정에 파일 핸들러가 여럿이다(wh1·intent_shadow). dictConfig는 FileHandler를 만들
    # 때 *즉시* 파일을 열므로, 대상 외 핸들러도 전부 tmp로 돌려 작업 트리에 로그 파일이 생기지
    # 않게 한다.
    for name, spec in config["handlers"].items():
        if "filename" in spec:
            spec["filename"] = str(tmp_path / f"{name}.log")
    config["handlers"]["wh1_record_file"]["filename"] = str(out)
    # 오염 스냅샷 — dictConfig는 설정의 loggers 키 각각에 propagate/disabled를 쓴다.
    # 구 버전은 finally가 핸들러만 복원해 propagate=False가 잔존했다(구 OPS-15 — pytest 8.x
    # caplog은 root 전용 부착이라 이후 caplog 단언이 0건 관측으로 연쇄 실패하는 순서 플레이크).
    # pytest 9+는 비전파 로거에도 직접 부착해 증상이 잠복하지만 오염 자체는 결함이다
    # (PED-25 ③ — 2026-08-15 결정론 프로브로 잔존 실측: dictConfig 후 propagate False).
    configured_loggers = list(config["loggers"])
    snapshot = {
        name: (logging.getLogger(name).propagate, logging.getLogger(name).disabled)
        for name in configured_loggers
    }
    handlers_before = {name: list(logging.getLogger(name).handlers) for name in configured_loggers}
    logging.config.dictConfig(config)
    try:
        logging.getLogger(_RECORD_LOGGER).info('{"probe": "e2e"}')
        for handler in logging.getLogger(_RECORD_LOGGER).handlers:
            handler.flush()
        assert out.read_text(encoding="utf-8").strip() == '{"probe": "e2e"}'
    finally:
        # 전역 로깅 상태 복원 — 핸들러뿐 아니라 propagate/disabled 스냅샷도 원복한다.
        # 핸들러는 *설정된 모든 로거*에서 걷어낸다(PED-48 — record 로거가 둘이 되면서, 한쪽만
        # 걷으면 다른 쪽 FileHandler가 남아 이후 테스트의 레코드를 tmp 파일로 빨아들인다).
        for name in configured_loggers:
            target = logging.getLogger(name)
            for handler in list(target.handlers):
                if handler not in handlers_before[name]:  # dictConfig가 붙인 것만 걷는다
                    target.removeHandler(handler)
                    handler.close()
        for name, (propagate, disabled) in snapshot.items():
            logger = logging.getLogger(name)
            logger.propagate = propagate
            logger.disabled = disabled


def test_logconfig_test_restores_logger_state(tmp_path: Path) -> None:
    """원복 회귀 동결 — 위 e2e 테스트가 propagate/disabled를 사전 상태로 되돌린다.

    변별력: 구 버전(핸들러만 복원)에선 이 테스트가 결정론적으로 실패한다(dictConfig가
    record 로거에 propagate=False를 잔존시키므로). 러너 버전·실행 순서와 무관하게 오염
    잔존을 직접 단언한다(pytest 9+의 caplog 마스킹과 무관한 축).
    """
    logger = logging.getLogger(_RECORD_LOGGER)
    before = (logger.propagate, logger.disabled)
    # PED-48: 설정된 *모든* 로거의 핸들러 수도 사전 상태로 돌아와야 한다(남은 FileHandler 차단)
    config = json.loads(_LOGCONFIG.read_text(encoding="ascii"))
    handler_counts = {n: len(logging.getLogger(n).handlers) for n in config["loggers"]}
    test_logconfig_captures_record_logger(tmp_path)
    assert {n: len(logging.getLogger(n).handlers) for n in config["loggers"]} == handler_counts
    after = (logger.propagate, logger.disabled)
    assert after == before, (
        f"dictConfig 테스트가 로거 상태를 잔존시켰습니다: {before} → {after}. "
        "finally에서 propagate/disabled 스냅샷 원복이 동작하는지 확인하세요."
    )


def test_logconfig_targets_real_record_logger_name() -> None:
    """설정의 로거 이름이 실물 wh1_shadow record 로거와 일치(재타이핑 드리프트 차단)."""
    from whymath_backend.harness import wh1_shadow

    config = json.loads(_LOGCONFIG.read_text(encoding="ascii"))
    assert _RECORD_LOGGER in config["loggers"]
    assert wh1_shadow.record_logger.name == _RECORD_LOGGER
