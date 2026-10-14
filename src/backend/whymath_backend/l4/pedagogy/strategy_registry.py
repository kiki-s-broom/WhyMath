"""교수전략 카탈로그 레지스트리 — 정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §3.

`pack_registry.py`(교수법 팩 인메모리 레지스트리)의 *교수전략 카탈로그* 짝이다 — 같은 하우스
스타일(코퍼스 YAML → `yaml.safe_load` + Pydantic 검증 → `@lru_cache(maxsize=1)` 인메모리 dict·
DB-free)로 `data/corpus/pedagogy_strategies_v1/*.yaml`(전략 10종·`PedagogyStrategy` enum 1:1)을
`strategy` 문자열 값("DIRECT")으로 키해 올린다.

특징(팩 레지스트리와 동일):
  - **인메모리·DB-free**: 첫 호출에만 파일을 읽고 이후는 0ms. 순수 값객체+YAML — DB·마이그레이션
    무관(카탈로그는 영속 테이블이 없는 *서술 자산*이라 L1 시더 좌석 자체가 없다는 점은 팩과 다름).
  - **계층 위생**: `schema`(카탈로그 계약)·`yaml`(로더)만 import — l4에서 schema만 내려다본다
    (import-linter `api→l6→l5→l4→l3→l2→l1→schema` 합치).
  - **경로 고정**: 레포 루트 기준(`parents[5]` — `pack_registry.py`와 동일 depth)으로 코퍼스
    디렉터리를 앵커해 cwd 무관하게 해석한다.

팩 레지스트리와의 의도적 차이 1개: 단건 조회 `get_strategy()`는 미등록 시 None(fail-soft)이
아니라 **`LookupError`를 던진다**(조용한 폴백 금지). 팩은 "없으면 base_system 그대로"라는 옵트인
계약이 실재하지만, 전략 카탈로그는 enum 10종과 1:1 완비가 거버넌스 테스트로 동결된 자산이라
미등록 조회는 곧 결함(오탈자·코퍼스 누락)이며 조용히 넘어가면 안 된다.

⚠️ 범위: 이 모듈은 **카탈로그 자산의 조회까지만** 제공한다. 소비 배선(`runtime_selector`의
select 후보 필터·`prompt_assembler` 전략 카드)은 **PED-23(회수 — 원 PED-06 재적용)이 착지**
했고, 카탈로그가 `gate()` 입력에 들어가면 안 된다는 불변식(04g §4 ②)도 같은 태스크의 테스트
(`tests/backend/l4/test_catalog_consumption.py`)가 동결한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from whymath_backend.schema.enums import PedagogyStrategy
from whymath_backend.schema.pedagogy_strategy import PedagogyStrategyCard

# 코퍼스 카탈로그 디렉터리 — 레포 루트 기준 고정(cwd 무관). 이 파일은
# src/backend/whymath_backend/l4/pedagogy/strategy_registry.py라 parents[5]가 레포 루트다
# (`pack_registry.py`가 같은 디렉터리에서 parents[5]로 같은 루트를 잡는 것과 동일 depth).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_STRATEGIES_DIR = _REPO_ROOT / "data" / "corpus" / "pedagogy_strategies_v1"


@lru_cache(maxsize=1)
def get_pedagogy_strategies() -> dict[str, PedagogyStrategyCard]:
    """전략 카탈로그 YAML을 검증·적재해 `strategy`(문자열) → 카드로 반환(1회 로드·캐시).

    `_STRATEGIES_DIR`의 `*.yaml`을 정렬 glob(결정적 순서)해 각각 `yaml.safe_load`(안전 로더·
    임의 객체 역직렬화 금지) 후 `PedagogyStrategyCard.model_validate`로 검증한다 — 폐쇄 어휘·
    빈 서술 등 카탈로그 불변식은 schema가 게이트하므로 오염 항목은 여기서 `ValidationError`로
    떨어진다(정직·조용한 실패 금지). `_provenance.json`은 `.yaml`이 아니라 glob에 안 잡힌다
    (표지 메타 제외). 키는 `use_enum_values=True`로 문자열이 된 `card.strategy`("DIRECT")다.
    enum 10종 ↔ YAML 10건 1:1은 거버넌스 테스트가 동결한다(레지스트리는 검증·적재만).

    Raises:
        FileNotFoundError: `_STRATEGIES_DIR`가 없거나 파일 접근 실패(경로 앵커 회귀 — 조용히
            삼키지 않는다).
        pydantic.ValidationError: 어느 항목이 schema 형식·카탈로그 불변식을 위반(게이트는
            schema 몫).
    """
    cards: dict[str, PedagogyStrategyCard] = {}
    for path in sorted(_STRATEGIES_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        card = PedagogyStrategyCard.model_validate(raw)
        # strategy는 use_enum_values=True라 문자열 값("DIRECT") — 그대로 dict 키.
        cards[str(card.strategy)] = card
    return cards


def get_strategy(strategy: PedagogyStrategy | str) -> PedagogyStrategyCard:
    """전략 1종의 카탈로그 카드 조회 — 미등록이면 `LookupError`(조용한 폴백 금지).

    `PedagogyStrategy` 멤버·문자열 값("DIRECT") 둘 다 받는다(enum은 str 혼합형이라 값으로
    정규화). 팩 레지스트리 `get_pack`의 None(fail-soft)과 달리 예외를 던지는 이유: 카탈로그는
    enum 10종 1:1 완비가 동결된 자산이라, 미등록 조회는 "미적용 신호"가 아니라 오탈자·코퍼스
    누락 **결함**이다 — 조용히 넘어가면 침묵 실패가 된다(모듈 docstring 참조).

    Raises:
        LookupError: 카탈로그에 없는 전략 키(오류 메시지에 요청 키·등록 키 목록 포함).
    """
    key = strategy.value if isinstance(strategy, PedagogyStrategy) else strategy
    cards = get_pedagogy_strategies()
    if key not in cards:
        raise LookupError(
            f"교수전략 카탈로그 미등록: {key!r} — 등록 키: {sorted(cards)}. "
            "(enum 1:1 완비 자산이라 미등록 조회는 결함입니다 — 오탈자·코퍼스 누락 확인)"
        )
    return cards[key]


def reset_strategy_cache() -> None:
    """레지스트리 캐시 무효화 — 테스트 격리용(코퍼스 교체·경로 변경 후 재로딩).

    `pack_registry.reset_pack_cache`와 동형 — 프로덕션 런타임은 카탈로그가 프로세스 수명 동안
    고정이라 호출할 일이 없다(테스트 전용 seam).
    """
    get_pedagogy_strategies.cache_clear()


__all__ = [
    "get_pedagogy_strategies",
    "get_strategy",
    "reset_strategy_cache",
]
