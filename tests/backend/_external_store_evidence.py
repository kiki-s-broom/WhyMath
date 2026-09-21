"""외부 store 매니페스트의 *실재 계약* — 선언된 store에 배포 근거가 있는지 기계 대조(SEC-32).

왜 이 모듈이 있는가
────────────────────────────────────────────────────────────────────────────
개인정보 삭제·반출 매니페스트(`privacy/erasure.external_erasure_targets`·
`privacy/export.external_export_pending`)는 "학생 데이터가 우리 DB 밖 어디에 있는가"를
선언한다 — 미성년 PII 처리의 *법적 근거 문서*다(CLAUDE.md 의사결정 우선순위 2위). 그런데
종전 회귀 테스트는 `{"clickhouse", "s3", "redis"}`라는 **하드코딩 집합**과의 일치만 봤다.
그 집합이 사실인지는 아무도 묻지 않았고, 실제로 두 store(ClickHouse·S3)는 이 저장소에
**도입된 적이 없다**(config 키 0·compose 서비스 0). 하드코딩 집합은 매니페스트를 *동결*할 뿐
*검증*하지 않는다 — 거짓을 그대로 동결한다.

이 모듈은 그 자리를 **계약**으로 바꾼다: *선언된 store는 배포 근거(설정 키 또는 compose
서비스)로 실재가 확인돼야 한다.* 근거가 없으면 그 store는 매니페스트에 있을 자격이 없다.

왜 문자열 금지 목록이 아니라 산출물 검사인가
────────────────────────────────────────────────────────────────────────────
"clickhouse라고 쓰지 마라" 형태의 금지 열거는 표기 변형(`click_house`·`ClickHouse`·
`analytics_store`)에서 그대로 뚫린다. 그래서 이 모듈은 **구성된 산출물**만 본다 —
`Settings.model_fields`(pydantic이 실제로 만든 필드 목록)와 compose YAML을 **파싱해서 얻은**
서비스·이미지·환경변수 키. 소스 텍스트 grep이 아니다.

이 구별은 이론이 아니다. 이 태스크의 사전 실측이 `grep -i s3 config.py`로 3건을 얻어 S3를
"파일럿 한정 도입"으로 판정했는데, 그 3건은 전부 **슬라이스 라벨**("S2가…", "S3가…",
"S3-32 —")이었고 `docker-compose.pilot.yml`의 1건도 주석 `# S3-01 파일럿 코호트`였다.
객체 저장소로서의 S3는 설정 키도 서비스도 SDK도 0건이다. YAML 파서는 주석을 애초에
보지 않고, `model_fields`는 문자열이 아니라 필드다 — 같은 착오가 구조적으로 불가능하다.

탐지기 자신의 변별력
────────────────────────────────────────────────────────────────────────────
전수 스캔 가드는 대상을 하나도 못 찾으면 *공허하게 통과*한다(CLAUDE.md "스캔 0건은 실패").
그래서 ①두 근거 원천 각각에 하한을 걸고 ②`assert_detector_is_discriminating()`이
"실재하는 store는 통과, 미도입 store는 불통"을 매 실행 확인한다 — 탐지기가 모든 입력에
같은 답을 내는 위장 상태를 스스로 잡는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import yaml

# 이 파일 = <repo>/tests/backend/_external_store_evidence.py → parents[2] = <repo>.
# cwd에 의존하지 않는다(백엔드 스위트는 `cd src/backend`에서도, 저장소 루트에서도 돈다).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_COMPOSE_GLOB: Final[str] = "docker-compose*.yml"

# 탐지기 자기검증용 표본 — 실재/미도입이 *현재* 사실인 store.
# 이 값이 깨지는 날(예: ClickHouse를 실제로 도입)은 탐지기 고장이 아니라 **매니페스트를
# 다시 볼 시점**이다. 그때 이 상수와 매니페스트를 함께 갱신하라(조용한 통과 금지).
KNOWN_DEPLOYED_STORE: Final[str] = "redis"
KNOWN_UNDEPLOYED_STORES: Final[tuple[str, ...]] = ("clickhouse", "s3")

# 스캔 0건 방어 하한 — 근거 원천이 비었는데 "근거 없음"으로 판정하면 계약이 뒤집힌다
# (실재하는 store까지 전부 불통이 되거나, 반대로 검사가 무의미해진다). 현행 실측은
# 설정 필드 110개·compose 서비스 6개(3파일)라 하한은 넉넉히 아래에 둔다.
_MIN_CONFIG_FIELDS: Final[int] = 50
_MIN_COMPOSE_SERVICES: Final[int] = 3

_TOKEN_SPLIT: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    """식별자를 소문자 토큰 집합으로 — `redis_url`→{redis,url}, `redis:7-alpine`→{redis,7,alpine}.

    부분문자열 매칭을 쓰지 않는 이유: `s3`가 `s3cret`·`aws3` 같은 무관한 문자열에 걸리고,
    반대로 토큰 경계를 지키면 "이름의 한 마디로 등장했는가"라는 훨씬 정확한 질문이 된다.
    """
    return frozenset(part for part in _TOKEN_SPLIT.split(text.lower()) if part)


def _config_evidence() -> dict[str, list[str]]:
    """`Settings`가 *실제로 정의한* 필드명에서 store 근거를 모은다(소스 텍스트 아님).

    설정 키가 있다는 것은 그 store에 붙을 좌석이 코드에 존재한다는 뜻이다 — 배포 근거 ①.
    """
    from whymath_backend.config import Settings

    fields = tuple(Settings.model_fields)
    if len(fields) < _MIN_CONFIG_FIELDS:
        raise AssertionError(
            f"설정 근거 스캔이 비었다(필드 {len(fields)}개 < 하한 {_MIN_CONFIG_FIELDS}) — "
            "Settings 로드가 깨졌을 때 '근거 없음'으로 오판하지 않도록 여기서 멈춘다."
        )
    index: dict[str, list[str]] = {}
    for name in fields:
        for token in _tokens(name):
            index.setdefault(token, []).append(f"config.Settings.{name}")
    return index


def _compose_files() -> tuple[Path, ...]:
    """저장소 루트의 compose 파일 목록. 스캔 실패·0건은 *실패*지 '없음'이 아니다.

    `glob`은 권한 거부 등에서 `OSError`를 던진다 — 삼키면 "compose에 아무 store도 없다"는
    거짓 결론이 조용히 나온다. 예외 타입명을 메시지에 남겨 원인을 지목한다(침묵 실패 금지).
    """
    try:
        files = tuple(sorted(_REPO_ROOT.glob(_COMPOSE_GLOB)))
    except OSError as exc:
        raise AssertionError(
            f"compose 파일 스캔 실패({_REPO_ROOT}) — {type(exc).__name__}: {exc}"
        ) from exc
    if not files:
        raise AssertionError(
            f"compose 파일 0건({_REPO_ROOT}/{_COMPOSE_GLOB}) — 스캔 0건은 실패다"
            "(대상을 못 찾은 가드는 공허하게 통과한다)."
        )
    return files


def _compose_evidence() -> dict[str, list[str]]:
    """compose YAML을 *파싱해* 서비스명·이미지·환경변수 키에서 store 근거를 모은다 — 배포 근거 ②.

    주석·산문은 보지 않는다(파서가 애초에 버린다). 환경변수 *값*도 제외한다 — 값에는 한국어
    안내문(`${...:?... 미설정 - ...}`)이 섞여 있어 우연한 토큰 일치를 만든다. 이름만 본다.
    """
    index: dict[str, list[str]] = {}
    service_count = 0
    for path in _compose_files():
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise AssertionError(
                f"compose 파싱 실패({path.name}) — {type(exc).__name__}: {exc}"
            ) from exc
        services = (document or {}).get("services") or {}
        if not isinstance(services, dict):
            raise AssertionError(
                f"compose 형식 예상 밖({path.name}) — services가 매핑이 아니다: {type(services).__name__}"
            )
        for name, spec in services.items():
            service_count += 1
            sources = [(f"{path.name}: services.{name}", name)]
            if isinstance(spec, dict):
                image = spec.get("image")
                if isinstance(image, str):
                    sources.append((f"{path.name}: services.{name}.image={image}", image))
                environment = spec.get("environment")
                # compose는 매핑(`KEY: value`)과 리스트(`- KEY=value`) 둘 다 허용한다.
                env_keys: list[str] = []
                if isinstance(environment, dict):
                    env_keys = [str(key) for key in environment]
                elif isinstance(environment, list):
                    env_keys = [str(entry).split("=", 1)[0] for entry in environment]
                for key in env_keys:
                    sources.append((f"{path.name}: services.{name}.environment.{key}", key))
            for label, text in sources:
                for token in _tokens(text):
                    index.setdefault(token, []).append(label)
    if service_count < _MIN_COMPOSE_SERVICES:
        raise AssertionError(
            f"compose 서비스 스캔이 비었다(서비스 {service_count}개 < 하한 "
            f"{_MIN_COMPOSE_SERVICES}) — 파싱이 깨진 상태를 '근거 없음'으로 오판하지 않는다."
        )
    return index


def evidence_for(store: str) -> tuple[str, ...]:
    """store 식별자의 배포 근거 목록(빈 튜플 = 이 저장소에 도입된 적 없음)."""
    token = store.strip().lower()
    found: list[str] = []
    for index in (_config_evidence(), _compose_evidence()):
        found.extend(index.get(token, ()))
    return tuple(found)


def assert_detector_is_discriminating() -> None:
    """탐지기 자신이 실재/미도입을 갈라내는지 매 실행 확인한다(위장 통과 방지).

    모든 입력에 "근거 있음"을 내는 탐지기도, 모든 입력에 "근거 없음"을 내는 탐지기도
    정상 상태에서는 초록으로 보인다 — 어느 쪽인지 여기서 양방향으로 못박는다.
    """
    deployed = evidence_for(KNOWN_DEPLOYED_STORE)
    assert deployed, (
        f"탐지기 고장 — 실배포 store '{KNOWN_DEPLOYED_STORE}'의 근거를 못 찾았다. "
        "이 상태면 매니페스트 계약이 실재하는 store까지 거짓으로 막는다."
    )
    for store in KNOWN_UNDEPLOYED_STORES:
        found = evidence_for(store)
        assert not found, (
            f"탐지기 변별력 상실 — 미도입 store '{store}'에서 근거가 나왔다: {found}. "
            "탐지기가 고장났거나, 그 store가 실제로 도입됐다(후자면 매니페스트를 갱신하라)."
        )


def assert_manifest_stores_are_deployed(stores: Iterable[str], *, source: str) -> None:
    """매니페스트가 선언한 store 전부에 배포 근거가 있어야 한다(허위 선언 차단).

    Args:
        stores: 매니페스트가 선언한 store 식별자들.
        source: 실패 메시지에 찍을 매니페스트 이름(어느 매니페스트가 거짓인지 지목).
    """
    assert_detector_is_discriminating()
    declared = tuple(stores)
    assert declared, (
        f"{source}: 선언된 store 0건 — 매니페스트가 비면 '외부 반출처 없음'을 주장하는 "
        "것과 같다. 실제로 없다면 이 계약 자체를 지워야 하고, 있다면 등재해야 한다."
    )
    unproven = {store: evidence_for(store) for store in declared}
    missing = sorted(store for store, found in unproven.items() if not found)
    assert not missing, (
        f"{source}: 배포 근거가 없는 store를 선언하고 있다 — {missing}. "
        "설정 키(config.Settings.*)도, compose 서비스/이미지/환경변수 키도 이 이름을 모른다. "
        "미도입 store를 삭제·반출 매니페스트에 적으면 법적 근거 문서가 거짓이 된다"
        "(SEC-32). 실재하면 근거를 배선하고, 아니면 매니페스트에서 빼라."
    )
