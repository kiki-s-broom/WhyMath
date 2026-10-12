"""`review_status` 각인 도구 2종의 **적용 대상 계약** — 코드 쪽 단일 정본 (EOS-136 ④).

왜 이 모듈이 있는가
------------------
문항 코퍼스의 `review_status`(학생 노출 가부 — `l6/_shared.is_review_cleared`가 `approved`만
통과시킨다)를 **쓰는 도구가 둘**이다:

  - 코퍼스 단위 백필 `harness/problem_corpus_review_status_backfill` — 고정 코퍼스의 감사 라벨
    표본(n ≥ 200)으로 **코퍼스 전체에 판정 1개**를 내리고 빈 레코드 전원에 채운다.
  - 사람 판정 각인 `harness/review_status_verdict_bridge` — 축적 CLI의 회차 코퍼스에 **slug별
    사람 최신 판정**을 옮긴다.

두 도구는 같은 축을 쓰고 둘 다 "이미 채워진 값은 덮어쓰지 않는다". 그래서 **먼저 쓴 쪽이 영구히
이긴다** — 코퍼스 단위 백필이 회차 코퍼스에 먼저 닿으면 사람 판정은 다시는 각인될 수 없고(빈
칸이 없다), 더 나쁘게는 다른 코퍼스의 감사 근거로 `approved`를 채워 **아무도 보지 않은 문항을
노출 가능**으로 만든다(`docs/reviews/mp03_canary_threshold_and_promotion_path_2026-09-25.md`
§4.2 "남의 감사 근거로 각인"). 두 도구의 대상을 겹치지 않게 가르는 규칙이 산문에만 있으면
그 사고는 조용히 난다. 이 모듈이 그 규칙을 **양쪽 도구가 import하는 술어**로 둔다.

코퍼스 부류 (분류 = `classify_corpus`)
-------------------------------------
  ``fixed``    고정 코퍼스 8종(`KNOWN_CORPORA` 경로) — 코퍼스 단위 백필의 대상.
  ``round``    회차 코퍼스 — 축적 CLI가 항상 남기는 회차 대장 사이드카(`<corpus>.rounds.jsonl` =
               `anchor_round_ledger.default_round_ledger_path`)가 실재한다. 사람 판정 각인의 대상.
  ``other``    그 밖(레포의 배치 코퍼스 30종 등) — **어느 도구의 대상도 아니다.** 빈
               `review_status` = 노출 차단(fail-closed)이 정상 상태다. 해금은 감사 라벨 표본을
               만들어 `KNOWN_CORPORA`·`AUDIT_LABEL_MAP`에 편입하는 것(코퍼스 단위)이고, 그 결정은
               이 계약 밖이다.
  ``conflict`` 고정 코퍼스 경로인데 회차 대장도 있다 — 계약 위반 상태(두 도구 모두 거부).
  ``unknown``  대장 사이드카의 실재를 확인할 수 없다(권한 등) — **모른다 ≠ 아니다**, 두 도구
               모두 거부한다.

회차 식별을 사이드카로 하는 이유: 회차 코퍼스는 레포에 상주하지 않고(운영자 머신의 `--out`)
이름도 자유다. 축적 CLI가 **끌 수 없게** 남기는 대장만이 "이 파일은 축적 회차의 산출물이다"를
말하는 내구 표식이다(`problem_corpus_accumulate` docstring "끄기 없음").

거부 규칙 (집행 지점 — 정본화와 별항)
------------------------------------
  - 코퍼스 단위 백필(`corpus_backfill_refusal`) — `round`·`conflict`·`unknown`이면 거부.
    그리고 **근거 차용 금지**: 코퍼스 키 K의 판정은 K의 코퍼스에만 적용한다 — 다른 고정 코퍼스
    경로나 레포 `data/corpus/` 아래의 다른 코퍼스에 K의 감사 근거를 쓰면 거부한다. `--all`의
    대상 전건에도 같은 검사를 걸어, 누군가 회차 코퍼스를 `KNOWN_CORPORA`에 등재하면 CI 드리프트
    가드(`--all --check`)가 **exit 2로 빨개진다**(가드가 회차 코퍼스를 "미백필 드리프트"로 오판해
    코퍼스 단위 각인을 권하는 대신).
  - 사람 판정 각인(`verdict_bridge_refusal`) — `round`가 아니면 거부.

두 도구의 거부는 모두 **입력 오류(exit 2)** 이고 아무것도 쓰지 않는다. 충돌 규칙(이미 채워진
값 불가침)과 각인 판정·④단 분모 판정까지의 계약 전문은
`docs/standards/review_status_stamping_contract.md`가 정본이다(이 모듈은 그중 *적용 대상*의
코드 착지다). harness는 import-linter 계약 밖(조성/ops 층 — 코퍼스 백필 선례).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from whymath_backend.harness.anchor_round_ledger import default_round_ledger_path
from whymath_backend.harness.problem_corpus_persona_fit_backfill import KNOWN_CORPORA

__all__ = [
    "CORPUS_KINDS",
    "CorpusKind",
    "classify_corpus",
    "corpus_backfill_refusal",
    "verdict_bridge_refusal",
]

CorpusKind = Literal["fixed", "round", "other", "conflict", "unknown"]

#: 분류 어휘(폐쇄 집합) — 계약 문서 표와 테스트가 이 튜플을 대조한다.
CORPUS_KINDS: tuple[CorpusKind, ...] = ("fixed", "round", "other", "conflict", "unknown")

# 레포 코퍼스 루트(레포 루트 기준 상대경로 — 두 도구 모두 "레포 루트에서 실행" 전제).
_REPO_CORPUS_DIR = Path("data/corpus")


def _ledger_presence(corpus_path: Path) -> tuple[bool | None, str | None]:
    """회차 대장 사이드카 실재 — (True/False, None) 또는 확인 불가 (None, 예외 타입명).

    `Path.is_file()`은 권한 거부(EACCES)를 False로 접지 않고 예외로 올린다(`pathlib`의 무시
    errno 집합에 EACCES가 없다 — CLAUDE.md 2026-09-01 ②). 그 예외를 "없다"로 읽으면 회차
    코퍼스가 고정 코퍼스처럼 통과하므로, 여기서는 **모른다**로 돌려준다.
    """
    try:
        return default_round_ledger_path(corpus_path).is_file(), None
    except OSError as exc:
        return None, type(exc).__name__


def _is_known_fixed(corpus_path: Path) -> bool:
    """고정 코퍼스 8종 경로 중 하나인가(레포 루트 기준 해석)."""
    resolved = corpus_path.resolve()
    return any(resolved == known.resolve() for known in KNOWN_CORPORA.values())


def classify_corpus(corpus_path: Path) -> tuple[CorpusKind, str | None]:
    """코퍼스 부류 판정 — (부류, `unknown`일 때 확인 실패 예외 타입명)."""
    has_ledger, error = _ledger_presence(corpus_path)
    if has_ledger is None:
        return "unknown", error
    fixed = _is_known_fixed(corpus_path)
    if fixed and has_ledger:
        return "conflict", None
    if fixed:
        return "fixed", None
    if has_ledger:
        return "round", None
    return "other", None


def corpus_backfill_refusal(in_path: Path, corpus_key: str) -> str | None:
    """코퍼스 단위 백필이 이 입력을 거부해야 하면 사유, 아니면 None.

    `corpus_key`가 `KNOWN_CORPORA`에 없으면 근거 차용 검사는 건너뛴다 — 그 키는 백필 CLI의
    `compute_corpus_verdict`가 `KeyError`로 따로 거부한다(오타 방지 — 여기서 중복 판정하지 않는다).
    """
    kind, error = classify_corpus(in_path)
    if kind == "unknown":
        return (
            f"{in_path}: 회차 대장 사이드카({default_round_ledger_path(in_path).name}) 실재를 "
            f"확인할 수 없다({error}) — 회차 코퍼스가 아님을 보일 수 없으면 코퍼스 단위 판정을 "
            "쓰지 않는다(모른다 ≠ 아니다)."
        )
    if kind in ("round", "conflict"):
        return (
            f"{in_path}: 회차 코퍼스다(회차 대장 {default_round_ledger_path(in_path).name} 실재) — "
            "코퍼스 단위 백필의 대상이 아니다. 회차 코퍼스의 review_status는 사람 판정 각인 도구"
            "(python -m whymath_backend.harness.review_status_verdict_bridge)로만 각인한다"
            "(EOS-136 · docs/standards/review_status_stamping_contract.md)."
        )
    expected = KNOWN_CORPORA.get(corpus_key)
    if expected is None:
        return None
    resolved = in_path.resolve()
    if resolved == expected.resolve():
        return None
    if kind == "fixed" or resolved.is_relative_to(_REPO_CORPUS_DIR.resolve()):
        return (
            f"{in_path}: 코퍼스 키 {corpus_key!r}의 코퍼스({expected})가 아니다 — 다른 코퍼스의 "
            "감사 근거로 각인하는 것(근거 차용)은 금지다. 감사 라벨이 없는 코퍼스는 빈 "
            "review_status(노출 차단)가 정상 상태다."
        )
    return None


def verdict_bridge_refusal(corpus_path: Path) -> str | None:
    """사람 판정 각인 도구가 이 코퍼스를 거부해야 하면 사유, 아니면 None(= 회차 코퍼스)."""
    kind, error = classify_corpus(corpus_path)
    ledger = default_round_ledger_path(corpus_path).name
    if kind == "round":
        return None
    if kind == "unknown":
        return (
            f"{corpus_path}: 회차 대장 사이드카({ledger}) 실재를 확인할 수 없다({error}) — "
            "회차 코퍼스임을 보일 수 없으면 각인하지 않는다(모른다 ≠ 아니다)."
        )
    if kind in ("fixed", "conflict"):
        return (
            f"{corpus_path}: 고정 코퍼스(KNOWN_CORPORA)다 — 코퍼스 단위 백필"
            "(problem_corpus_review_status_backfill)의 대상이며 사람 판정 각인 대상이 아니다."
        )
    return (
        f"{corpus_path}: 회차 코퍼스가 아니다(회차 대장 {ledger} 없음) — 사람 판정 각인은 축적 "
        "CLI(problem_corpus_accumulate)의 회차 코퍼스에만 쓴다. 그 밖의 코퍼스는 어느 각인 "
        "도구의 대상도 아니다(빈 review_status = 노출 차단이 정상)."
    )
