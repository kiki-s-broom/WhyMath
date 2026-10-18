"""오답 서명 규칙표 로더 + kebab ↔ M-id 코퍼스 조회 (P3-56 후보 구현) — DB 없는 순수 읽기.

YAML 자산(`data/corpus/wrong_answer_signatures_v1/rules.yaml`)을 `schema.wrong_answer_signature`
계약으로 검증해 올린다. 첫 호출에만 파일을 읽고 이후는 인메모리다(`strategy_registry` 하우스
스타일).

kebab ↔ M-id 조회를 여기 두는 이유
────────────────────────────────────────────────────────────────────────────
런타임 후보는 kebab id로 나오고(학생 데이터 키), 규칙표는 M-id를 가리킨다. 둘을 잇는 정본은
승인 크로스워크 코퍼스(`misconception_crosslinks_v1/crosslinks.json`)다. 기존 resolver
(`crosslink_resolve.MisconceptionCrosslinkResolver`)는 DB 엔진을 요구하고 **M-id → kebab 방향이
없다**(2026-10-16 코드 지도 실측 — 검색어 `mis_to_kebab`·`kebab_for_mis`·`by_mis_id` 0건). 그래서
같은 코퍼스를 DB 없이 읽는 조회를 여기 둔다. 매핑을 새로 만드는 것이 아니라 **같은 파일을 다른
방향으로 읽는 것**이며, canonical 선정은 기존 순수 함수 `select_canonical`을 그대로 재사용한다
(정책 사본 0).

fail-closed
────────────────────────────────────────────────────────────────────────────
파일이 없거나 형식이 틀리면 조용히 빈 표를 돌려주지 않고 예외를 낸다. 빈 표는 "규칙이 없다"와
구별되지 않아 전 구간이 NOT_RUN으로 위장된다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml

from whymath_backend.l1.misconception.crosslink_resolve import ResolvedLink, select_canonical
from whymath_backend.schema.wrong_answer_signature import SignatureSpec

__all__ = [
    "SIGNATURE_RULES_PATH",
    "CROSSLINKS_PATH",
    "canonical_mis_id_for_kebab",
    "kebab_for_mis_id",
    "load_signature_spec",
    "mis_ids_for_kebab",
]

# 이 파일은 src/backend/whymath_backend/l1/misconception/*.py라 parents[5]가 레포 루트다
# (`l4/pedagogy/strategy_registry.py`가 같은 depth에서 parents[5]로 같은 루트를 잡는다).
_REPO_ROOT = Path(__file__).resolve().parents[5]
SIGNATURE_RULES_PATH = _REPO_ROOT / "data" / "corpus" / "wrong_answer_signatures_v1" / "rules.yaml"
CROSSLINKS_PATH = _REPO_ROOT / "data" / "corpus" / "misconception_crosslinks_v1" / "crosslinks.json"


@lru_cache(maxsize=1)
def load_signature_spec() -> SignatureSpec:
    """서명 규칙표를 검증·적재한다(1회 로드·캐시).

    Raises:
        FileNotFoundError: 표 파일이 없다(경로 앵커 회귀를 삼키지 않는다).
        pydantic.ValidationError: 계약 위반(형식·신뢰도 상한·중복 id).
    """
    raw = yaml.safe_load(SIGNATURE_RULES_PATH.read_text(encoding="utf-8"))
    return SignatureSpec.model_validate(raw)


@lru_cache(maxsize=1)
def _crosslink_links() -> tuple[tuple[str, str, str, float | None], ...]:
    """승인 코퍼스의 `(kebab_id, mis_id, link_type, confidence)` 전량 — 정렬된 불변 튜플."""
    payload = json.loads(CROSSLINKS_PATH.read_text(encoding="utf-8"))
    rows = payload["crosslinks"]
    if not rows:
        # 0건 스캔은 실패다 — 빈 코퍼스를 "매핑 없음"으로 읽으면 전 구간이 조용히 비어 버린다.
        raise ValueError(f"{CROSSLINKS_PATH}: crosslinks가 비어 있습니다")
    links = [
        (
            str(r["kebab_id"]),
            str(r["mis_id"]),
            str(r["link_type"]),
            None if r.get("confidence") is None else float(r["confidence"]),
        )
        for r in rows
    ]
    return tuple(sorted(links, key=lambda t: (t[0], t[1])))


def mis_ids_for_kebab(kebab_id: str) -> tuple[str, ...]:
    """kebab에 직접 걸린 M-id들 — 정렬·중복 제거. 링크가 없으면 빈 튜플."""
    return tuple(sorted({m for k, m, _, _ in _crosslink_links() if k == kebab_id}))


def kebab_for_mis_id(mis_id: str) -> str | None:
    """M-id가 걸린 kebab — **정확히 하나일 때만** 돌려준다(없거나 여럿이면 `None`).

    여럿이면 어느 kebab이 이 오개념의 런타임 키인지 코퍼스가 정하지 않은 것이므로 임의로
    고르지 않는다(오귀속 방지 — `select_canonical`이 동률을 미선정하는 것과 같은 보수).
    """
    kebabs = {k for k, m, _, _ in _crosslink_links() if m == mis_id}
    if len(kebabs) != 1:
        return None
    return next(iter(kebabs))


def canonical_mis_id_for_kebab(kebab_id: str) -> str | None:
    """kebab의 canonical M-id — 기존 `select_canonical` 정책 그대로(동률·직접매핑 부재는 `None`)."""
    links = [
        ResolvedLink(mis_id=m, link_type=t, confidence=c)
        for k, m, t, c in _crosslink_links()
        if k == kebab_id
    ]
    return select_canonical(links).canonical_mis_id
