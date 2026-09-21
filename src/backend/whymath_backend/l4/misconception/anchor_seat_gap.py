"""EOS G0 앵커 × misconceptions_v1 M-id × crosslinks kebab **좌석 갭** 측정 (MISC-21).

이 모듈이 있는 이유
-------------------
MISC-07(앵커 커버 오개념 기계판정 채널) 작업 중 실측으로 드러난 별건이다 — G0 확정 6앵커
(A1~A6, `l1/standards/anchor_registry.py`) 중 A1(초3 분수)·A2(초6 비와 비율)·A3(중2 경우의
수와 확률)·A5(고1 이차함수 최대·최소)는 misconceptions_v1(M-id 체계)에 오개념이 *존재*하는데도
crosslinks(kebab-id ↔ M-id, `crosswalk_gate_contract.md` 정본)에 **단 하나도 연결되지 않았다**.
"오개념이 없다"가 아니라 "두 ID 체계 사이 연결이 안 됐다"는 사실을 조인 경로 그대로 재현해
수치로 남기는 것이 이 모듈의 유일한 목적이다(간접 신호 아닌 조인 경로 자체를 측정 — CLAUDE.md
"간접 신호를 성공 판정으로 쓰는 안내 금지"·"변별력 없는 검증 스텝 금지").

경로(정직 재현) — 정확히 이 3단계, 다른 지름길 없음
------------------------------------------------
    앵커 코드(`anchors.yaml`) → misconceptions_v1 M-id(`standard_code` 일치)
    → crosslinks.json의 kebab_id(`mis_id` 일치, **사람 서명·적재 완료분만** — 검수 큐 후보 제외)

"좌석"(seat) = 앵커에 걸린 M-id 중 crosslinks.json에 실제로 연결된 **distinct kebab_id 수**.
검수 큐(`misconception_crosslink_review_queue.json`)의 pending 후보는 좌석이 아니다 — 사람
승인(reviewer·reviewed_on 서명) 후 `promote --load`를 거쳐 crosslinks.json에 실린 것만 좌석이다
(AI 자기승인 금지 — `docs/standards/crosswalk_gate_contract.md`).

판별력(변별력) 보장
-------------------
`compute_seat_gap`은 좌석 유무를 **입력 데이터만으로** 판정하는 순수 함수다(파일 I/O 없음) —
따라서 crosslinks 입력에서 행을 지우면 좌석 수가 실제로 줄고, 되돌리면 실제로 늘어난다(항상
같은 값을 내는 위장 검사가 아님 — CLAUDE.md "변별력 없는 검증 스텝 금지"). `tests/backend/l4/
test_anchor_seat_gap.py`가 커밋된 실 코퍼스로 이 실측(A1=0·A2=0·A3=0·A4=3·A5=0·A6=2 좌석,
M-id는 A1=4·A2=2·A3=4·A4=8·A5=2·A6=8)을 재현하고, 합성 좌석 추가/제거 양쪽에서 카운트가
달라짐을 뮤테이션 스타일로 확인한다.

계층 경계
---------
L4(교수학 엔진) — L1 코퍼스(성취기준·오개념·crosslinks)를 *읽기만* 하고 쓰지 않는다. 판정·적재는
하지 않는다(read-only 측정·리포트 전용, `crosslink_coverage.py`·`crosslink_review_aid.py`와 동형).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from whymath_backend.l1.standards.anchor_registry import (
    SCOPE_DECEMBER_2026,
    Anchor,
    AnchorRegistryError,
    default_registry_path,
    load_anchor_registry,
)

# anchor_seat_gap.py → parents[5]가 레포 루트(anchor_registry.py와 동일 깊이 관용구).
_REPO_ROOT = Path(__file__).resolve().parents[5]

DEFAULT_MISCONCEPTIONS_PATH = "data/corpus/misconceptions_v1/misconceptions.json"
#: **사람 서명·적재 완료** crosslinks(정본) — 검수 큐(pending 후보)와 다르다. 이 경로만
#: "좌석"으로 인정한다(crosswalk_gate_contract.md load_gate 통과분).
DEFAULT_CROSSLINKS_PATH = "data/corpus/misconception_crosslinks_v1/crosslinks.json"


class AnchorSeatGapError(RuntimeError):
    """입력 코퍼스 적재·구조 검증 실패 — 조용한 0건 대신 던진다(침묵 실패 금지)."""


class AnchorSeatCount(BaseModel):
    """앵커 1건의 좌석 갭 — M-id 존재량과 crosslinks 연결량을 함께 나른다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    anchor_id: str
    title: str
    scope: str
    codes: tuple[str, ...]
    #: 앵커 코드에 걸린 M-id(정렬·중복 없음) — "오개념이 존재하는가"의 답.
    mis_ids: tuple[str, ...]
    #: crosslinks.json으로 실제 연결된 (kebab_id, mis_id) 쌍 — "좌석이 있는가"의 답.
    seated_pairs: tuple[tuple[str, str], ...]
    #: crosslinks 연결이 없는 M-id(정렬) — 존재하지만 미연결(좌석 갭의 실체).
    unseated_mis_ids: tuple[str, ...]

    @property
    def mis_id_count(self) -> int:
        """앵커 코드에 걸린 M-id 총수."""
        return len(self.mis_ids)

    @property
    def seat_count(self) -> int:
        """crosslinks로 실제 연결된 distinct kebab_id 수 — 이 모듈이 재는 "좌석" 그 자체."""
        return len({kebab for kebab, _ in self.seated_pairs})

    @property
    def seated_kebab_ids(self) -> tuple[str, ...]:
        return tuple(sorted({kebab for kebab, _ in self.seated_pairs}))

    def to_json(self) -> dict[str, object]:
        return {
            "anchor_id": self.anchor_id,
            "title": self.title,
            "scope": self.scope,
            "codes": list(self.codes),
            "mis_id_count": self.mis_id_count,
            "mis_ids": list(self.mis_ids),
            "seat_count": self.seat_count,
            "seated_kebab_ids": list(self.seated_kebab_ids),
            "unseated_mis_ids": list(self.unseated_mis_ids),
        }


def compute_seat_gap(
    anchors: Iterable[Anchor],
    misconceptions: Iterable[Mapping[str, Any]],
    crosslinks: Iterable[Mapping[str, Any]],
) -> tuple[AnchorSeatCount, ...]:
    """앵커 코드 → M-id → crosslinks kebab 경로를 그대로 조인하는 순수 함수(I/O 없음).

    이 함수가 파일을 읽지 않는 이유 — **판별력**을 코드로 보장하기 위해서다. 입력을 합성해
    좌석이 있는 상태·없는 상태를 직접 만들 수 있어야 "이 검사가 실제로 구별하는가"를 뮤테이션
    스타일로 확인할 수 있다(CLAUDE.md "변별력 없는 검증 스텝 금지").
    """
    # PR #1068 Codex P2: 필수 필드 누락은 *조용히 건너뛰지* 않고 던진다. 이 모듈은 fail-closed
    # 측정기라 선언했다(docstring "판별력 보장") — 스키마 드리프트·부분 생성 코퍼스를 조용히
    # 삼키면 "좌석이 진짜로 0"과 "데이터가 깨져서 못 읽었다"가 같은 출력(0건)으로 보여, 진짜
    # 좌석 갭인 척 오판정을 낳는다.
    mis_ids_by_code: dict[str, list[str]] = {}
    for idx, record in enumerate(misconceptions):
        code = record.get("standard_code")
        mid = record.get("mis_id")
        if not code or not mid:
            raise AnchorSeatGapError(
                f"misconceptions[{idx}]: standard_code·mis_id 필수 필드 누락 — {record!r}"
            )
        mis_ids_by_code.setdefault(str(code), []).append(str(mid))

    kebabs_by_mid: dict[str, list[str]] = {}
    for idx, row in enumerate(crosslinks):
        mid = row.get("mis_id")
        kebab = row.get("kebab_id")
        if not mid or not kebab:
            raise AnchorSeatGapError(f"crosslinks[{idx}]: mis_id·kebab_id 필수 필드 누락 — {row!r}")
        kebabs_by_mid.setdefault(str(mid), []).append(str(kebab))

    results: list[AnchorSeatCount] = []
    for anchor in anchors:
        mis_ids = sorted({mid for code in anchor.codes for mid in mis_ids_by_code.get(code, ())})
        seated_pairs: list[tuple[str, str]] = []
        unseated: list[str] = []
        for mid in mis_ids:
            kebabs = sorted(set(kebabs_by_mid.get(mid, ())))
            if kebabs:
                seated_pairs.extend((kebab, mid) for kebab in kebabs)
            else:
                unseated.append(mid)
        results.append(
            AnchorSeatCount(
                anchor_id=anchor.id,
                title=anchor.title,
                scope=anchor.scope,
                codes=anchor.codes,
                mis_ids=tuple(mis_ids),
                seated_pairs=tuple(seated_pairs),
                unseated_mis_ids=tuple(unseated),
            )
        )
    return tuple(results)


def _load_json_list(path: Path, *, top_key: str) -> list[dict[str, Any]]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnchorSeatGapError(
            f"코퍼스를 읽지 못했다 ({path}): {type(exc).__name__}: {exc}"
        ) from exc
    try:
        doc = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AnchorSeatGapError(f"JSON 파싱 실패 ({path}): {type(exc).__name__}: {exc}") from exc
    if not isinstance(doc, dict) or top_key not in doc:
        raise AnchorSeatGapError(f"{path}: 최상위 {top_key!r} 배열이 없다")
    rows = doc[top_key]
    if not isinstance(rows, list):
        raise AnchorSeatGapError(f"{path}: {top_key!r}가 리스트가 아니다")
    return rows


def load_and_compute(
    *,
    registry_path: Path | None = None,
    misconceptions_path: Path | None = None,
    crosslinks_path: Path | None = None,
    scope: str = SCOPE_DECEMBER_2026,
) -> tuple[AnchorSeatCount, ...]:
    """실 코퍼스 3종을 읽어 `compute_seat_gap` 실행 — CLI·테스트 공용 진입점.

    실패는 전부 `AnchorSeatGapError`(또는 레지스트리 쪽은 `AnchorRegistryError`)로 명시 실패한다
    — "못 읽었으니 좌석 0건, 위반 없음"으로 통과시키지 않는다(침묵 실패 금지).
    """
    try:
        registry = load_anchor_registry(registry_path or default_registry_path())
    except AnchorRegistryError as exc:
        raise AnchorSeatGapError(f"앵커 레지스트리 적재 실패: {exc}") from exc
    anchors = registry.in_scope(scope)

    mis_path = misconceptions_path or (_REPO_ROOT / DEFAULT_MISCONCEPTIONS_PATH)
    xlink_path = crosslinks_path or (_REPO_ROOT / DEFAULT_CROSSLINKS_PATH)
    misconceptions = _load_json_list(mis_path, top_key="misconceptions")
    crosslinks = _load_json_list(xlink_path, top_key="crosslinks")

    return compute_seat_gap(anchors, misconceptions, crosslinks)


# ──────────────────────────────────────────────────────────────────────────
# CLI — read-only 측정·리포트(승인·적재·판정 없음). 판정은 exit 0=성공·1=적재 실패
# (게이트가 아니라 리포트이므로 좌석 0건 자체는 실패가 아니다 — crosslink_coverage.py 동형).
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l4.misconception.anchor_seat_gap",
        description=(
            "EOS G0 앵커 → misconceptions_v1 M-id → crosslinks kebab 경로로 앵커별 좌석 수를 "
            "측정하는 read-only 리포트(MISC-21). 승인·적재·판정 없음."
        ),
    )
    parser.add_argument("--registry", type=Path, default=None, help="앵커 레지스트리 YAML 경로")
    parser.add_argument("--misconceptions", type=Path, default=None, help="misconceptions_v1 JSON")
    parser.add_argument(
        "--crosslinks", type=Path, default=None, help="crosslinks.json(적재 완료분)"
    )
    parser.add_argument(
        "--scope",
        default=SCOPE_DECEMBER_2026,
        help=f"앵커 scope 필터(기본 {SCOPE_DECEMBER_2026})",
    )
    parser.add_argument("--json", action="store_true", help="리포트 JSON만 출력.")
    args = parser.parse_args(argv)

    try:
        results = load_and_compute(
            registry_path=args.registry,
            misconceptions_path=args.misconceptions,
            crosslinks_path=args.crosslinks,
            scope=args.scope,
        )
    except (AnchorSeatGapError, AnchorRegistryError) as exc:
        print(f"[적재 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        json.dump([r.to_json() for r in results], sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"앵커 좌석 갭 — scope={args.scope} ({len(results)}건)")
        for r in results:
            mark = "좌석 0" if r.seat_count == 0 else f"좌석 {r.seat_count}"
            print(
                f"  [{r.anchor_id}] {r.title}: M-id {r.mis_id_count}건 · {mark} "
                f"(kebab {list(r.seated_kebab_ids)})"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
