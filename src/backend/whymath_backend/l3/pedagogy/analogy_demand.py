"""비유·예시 수요 실측 CLI — 정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §6.1.

생성기의 발주 근거(select-vs-generate)를 **실측**한다 — 추론·가정 발주 금지(04g §6.4 사전 대량
생성 금지의 측정 짝). 세 축을 계수한다:

  ① **metaphor 공백** — `concept_content` 자산(코퍼스 846행)에서 metaphor가 비어 렌더 불가
     (`ConceptDSL.intuition` None → AnalogyAdapter `can_render` False)인 건수.
  ② **ai_estimated(저품질)** — 적재 시 전량 `review_status='ai_estimated'`로 박히는 건수
     (적재기 `l1/concept_content/projection.py`가 코퍼스에서 읽지 않고 상수로 각인 — 코퍼스에
     review_status 필드 자체가 없다). 추가로 규칙 검출기(`analogy_checker`)를 846행 전량에
     태워 **규칙 검출 결함 보유 건수**(축별)를 실측한다 — 이것이 재저작 발주의 실제 표적이며,
     게임형(GAMIFIED) 축 계수는 기존 자산의 "게임형 산출 0 검사" 실측이다.
  ③ **발주서 잔여 슬롯** — `data/corpus/units_v1/*.unit.yaml`을 컴파일해 발주 총량을 슬롯
     유형별로 계수한다. **승인(APPROVED) 채움 수는 DB 소관**이라 이 컨테이너(DB 없음)에서는
     `filled=None`으로 정직하게 비운다(표본 0을 0%로 위장 금지 — 하우스 스타일). 잔여 상한 =
     발주 총량(채움 실측은 Phaiakes9 런북에서 `--with-db`로).

측정 원천이 코퍼스 파일(정본 소스·hermetic)인 이유: `concept_content` 테이블은 코퍼스의 멱등
프로젝션이라(적재기 docstring) 코퍼스 계수 = 적재 직후 DB 계수다. DB가 코퍼스보다 앞선 상태
(검수 승격·기계 채움 후)의 계수는 `--with-db`(Phaiakes9)로 실측한다 — 실패는 예외 타입명을
로그에 남기고 None으로 표기한다(침묵 실패 금지).

7계층: L3(생성 계층의 수요 측정). L1 로더·컴파일러를 하향 재사용한다(역방향 금지 준수).

사용:
    # hermetic(코퍼스만·이 컨테이너에서 완결)
    python -m whymath_backend.l3.pedagogy.analogy_demand
    # DB 채움 현황까지(Phaiakes9 — prod DB 5433)
    python -m whymath_backend.l3.pedagogy.analogy_demand --with-db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from whymath_backend.l1.concept_content.projection import (
    ConceptContentRecord,
    load_concept_content_from_json,
)
from whymath_backend.l1.pedagogy.unit_compiler import (
    compile_unit,
    load_packs,
    load_statements_by_code,
    load_valid_atom_codes,
)
from whymath_backend.l3.pedagogy.analogy_checker import check_analogy_defects
from whymath_backend.l3.pedagogy.slot_generator import NUMERIC_SLOT_TYPES

_LOGGER = logging.getLogger(__name__)

_EXIT_OK: Final[int] = 0
_EXIT_INPUT_MISSING: Final[int] = 2

# 코퍼스 경로 — 레포 루트 기준 고정(cwd 무관·compile.py `parents[5]` 동형 depth).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTENT_K12 = _REPO_ROOT / "data" / "corpus" / "concept_content_v1" / "content.json"
_CONTENT_UNIV = _REPO_ROOT / "data" / "corpus" / "concept_content_university_v1" / "content.json"
_UNITS_DIR = _REPO_ROOT / "data" / "corpus" / "units_v1"
_ATOM_GRAPH = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_STANDARDS = _REPO_ROOT / "data" / "corpus" / "standards_v1" / "standards.json"
_PACKS_DIR = _REPO_ROOT / "data" / "corpus" / "pedagogy_packs_v1"


# ──────────────────────────────────────────────────────────────────────────
# ①② metaphor 수요 실측 (코퍼스 846행 — hermetic)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MetaphorDemand:
    """metaphor 축 실측 — 총량·공백·ai_estimated·규칙 결함(축별)·발주 표적 수."""

    total: int
    blank: int  # ① metaphor 공백(렌더 불가)
    ai_estimated: int  # ② 적재 시 review_status='ai_estimated'가 되는 건수(전량 — 상수 각인)
    defect_rows: int  # ② 규칙 검출 결함을 1개 이상 보유한 행(재저작 실표적)
    defect_by_axis: dict[str, int] = field(default_factory=dict)  # 축별 결함 행 수
    gamified_rows: int = 0  # 게임형 축 계수 — 기존 자산 "게임형 산출 0 검사" 실측


def load_all_content_records() -> list[ConceptContentRecord]:
    """콘텐츠 코퍼스 2편(K-12 437 + 대학 409) 전량 로드 — 적재기와 동일 로더 재사용(계수 동형).

    Raises:
        FileNotFoundError: 코퍼스 파일 부재(경로 앵커 회귀 — 조용히 삼키지 않는다).
    """
    records = load_concept_content_from_json(_CONTENT_K12, scope="K-12")
    records += load_concept_content_from_json(_CONTENT_UNIV, scope="대학")
    return records


def measure_metaphor_demand(records: list[ConceptContentRecord]) -> MetaphorDemand:
    """metaphor 축 계수(순수) — 공백·결함(축별)·게임형을 규칙 검출기로 실측.

    `ai_estimated`는 적재기 상수 각인 규약상 **전량**이다(코퍼스에 review_status 필드 부재 —
    모듈 docstring ②). 결함 계수는 metaphor 보유 행에만 검출기를 태운다(공백 행은 ①에 계상).
    """
    blank = 0
    defect_rows = 0
    axis_counter: Counter[str] = Counter()
    gamified = 0
    for record in records:
        text = (record.metaphor or "").strip()
        if not text:
            blank += 1
            continue
        defects = check_analogy_defects(text)
        if defects:
            defect_rows += 1
            axis_counter.update(defects)
            if "GAMIFIED" in defects:
                gamified += 1
    return MetaphorDemand(
        total=len(records),
        blank=blank,
        ai_estimated=len(records),  # 적재 상수 각인 — 전량(projection.py 규약)
        defect_rows=defect_rows,
        defect_by_axis=dict(sorted(axis_counter.items())),
        gamified_rows=gamified,
    )


# ──────────────────────────────────────────────────────────────────────────
# ③ 발주서 잔여 슬롯 실측 (units_v1 컴파일 — hermetic / 채움은 DB 옵션)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SlotDemand:
    """발주서 축 실측 — 슬롯 유형별 발주 총량 + 채움(DB 미접속 시 None·정직한 공백)."""

    units: int  # 컴파일한 소단원 수
    ordered_total: int  # 발주 총량(전 유형)
    ordered_by_type: dict[str, int]  # 슬롯 유형 → 발주 수
    conceptual_total: int  # 개념형(예시 생성기 표적 — NUMERIC 밖) 발주 수
    numeric_total: int  # 숫자형(동등문제 생성기 소관) 발주 수
    filled_by_type: dict[str, int] | None  # APPROVED 채움 수(DB) — 미측정이면 None(0 위장 금지)


def measure_slot_demand() -> SlotDemand:
    """units_v1 전 소단원을 컴파일해 발주 슬롯을 유형별 계수(hermetic — DB 0).

    채움(APPROVED) 계수는 여기서 하지 않는다 — `filled_by_type=None`(측정 좌석은
    `measure_filled_slots`·DB 옵트인). 컴파일 실패는 전파한다(발주서가 안 나오면 수요 측정
    자체가 무의미 — 조용한 부분 집계 금지).

    Raises:
        FileNotFoundError: units/packs/atom/standards 코퍼스 부재.
    """
    packs = load_packs(_PACKS_DIR)
    atom_codes = load_valid_atom_codes(_ATOM_GRAPH)
    statements = load_statements_by_code(_STANDARDS)
    ordered: Counter[str] = Counter()
    units = 0
    for unit_path in sorted(_UNITS_DIR.glob("*.unit.yaml")):
        compiled = compile_unit(
            unit_path.read_text(encoding="utf-8"),
            packs=packs,
            valid_atom_codes=atom_codes,
            statements_by_code=statements,
        )
        units += 1
        for item in compiled.work_order:
            ordered[str(item["slot_type"])] += int(item["count"])
    conceptual = sum(n for t, n in ordered.items() if t not in NUMERIC_SLOT_TYPES)
    numeric = sum(n for t, n in ordered.items() if t in NUMERIC_SLOT_TYPES)
    return SlotDemand(
        units=units,
        ordered_total=sum(ordered.values()),
        ordered_by_type=dict(sorted(ordered.items())),
        conceptual_total=conceptual,
        numeric_total=numeric,
        filled_by_type=None,  # DB 미접속 — 채움 미측정(None·0% 위장 금지)
    )


def measure_filled_slots() -> dict[str, int] | None:
    """DB의 APPROVED 슬롯 수를 유형별 계수(옵트인) — 실패는 None + 예외 타입명 로그.

    Phaiakes9 prod DB(5433) 전용 좌석이다. 이 컨테이너에는 DB가 없어 기본 경로는 호출조차
    하지 않으며(--with-db 옵트인), 접속 실패를 조용히 0으로 위장하지 않는다(침묵 실패 금지 —
    None은 "미측정"이지 "0건"이 아니다).
    """
    try:
        from sqlalchemy import func, select

        from whymath_backend.config import get_settings
        from whymath_backend.db.models.pedagogy_dsl import PedagogyContentSlot
        from whymath_backend.l1.embedding_primitives import build_sync_engine

        engine = build_sync_engine(get_settings())
        stmt = (
            select(PedagogyContentSlot.slot_type, func.count())
            .where(PedagogyContentSlot.status == "APPROVED")
            .group_by(PedagogyContentSlot.slot_type)
        )
        with engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return {str(slot_type): int(count) for slot_type, count in rows}
    except Exception as exc:  # noqa: BLE001 — DB 미가용은 예상 상황(측정 실패를 값으로 위장 금지)
        _LOGGER.warning("APPROVED 슬롯 DB 계수 실패(%s) — filled=None(미측정)", type(exc).__name__)
        return None


# ──────────────────────────────────────────────────────────────────────────
# 보고 렌더 + CLI
# ──────────────────────────────────────────────────────────────────────────
def render_report(metaphor: MetaphorDemand, slots: SlotDemand) -> str:
    """사람용 수요 실측 보고 — 발주 근거 3축(공백·저품질·잔여 슬롯)을 한 화면에."""
    lines = ["=" * 64, "비유·예시 생성 수요 실측 (PED-09 · 04g §6.1)", "=" * 64]
    lines.append(f"[① metaphor 공백] {metaphor.blank}건 / 총 {metaphor.total}행")
    lines.append(
        f"[② ai_estimated(저품질)] {metaphor.ai_estimated}건 — 적재 시 전량 상수 각인"
        "(projection.py·검수 전)"
    )
    lines.append(
        f"  규칙 검출 결함 보유(재저작 실표적): {metaphor.defect_rows}건"
        f" / 검사 대상 {metaphor.total - metaphor.blank}건"
    )
    for axis, count in metaphor.defect_by_axis.items():
        lines.append(f"    - {axis}: {count}건")
    lines.append(
        f"  게임형(GAMIFIED) 축 실측: {metaphor.gamified_rows}건 — 기존 자산 게임형 산출 검사"
    )
    lines.append(
        f"[③ 발주서 슬롯] 소단원 {slots.units}편 · 발주 총 {slots.ordered_total}점"
        f" (개념형 {slots.conceptual_total} · 숫자형 {slots.numeric_total})"
    )
    for slot_type, count in slots.ordered_by_type.items():
        kind = "숫자형" if slot_type in NUMERIC_SLOT_TYPES else "개념형"
        lines.append(f"    - {slot_type} ({kind}): 발주 {count}")
    if slots.filled_by_type is None:
        lines.append(
            "  APPROVED 채움: 미측정(None — DB 미접속·이 환경엔 DB 없음). "
            "잔여 상한 = 발주 총량. 채움 실측은 Phaiakes9 `--with-db`."
        )
    else:
        filled_total = sum(slots.filled_by_type.values())
        lines.append(f"  APPROVED 채움: {filled_total}점 (유형별 {slots.filled_by_type})")
        remaining = slots.ordered_total - filled_total
        lines.append(f"  잔여 슬롯: {remaining}점")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """수요 실측 CLI 본체 — 코퍼스 계수(항상) + DB 채움 계수(옵트인). exit 0=측정 완료."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l3.pedagogy.analogy_demand",
        description=(
            "비유·예시 생성 수요 실측 — metaphor 공백/저품질·발주서 잔여 슬롯을 코퍼스에서 "
            "계수한다(hermetic). --with-db면 APPROVED 채움 현황까지(Phaiakes9)."
        ),
    )
    parser.add_argument(
        "--with-db",
        action="store_true",
        help="APPROVED 슬롯 채움 수를 DB에서 계수(Phaiakes9 전용 — 실패 시 None·타입명 로그).",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로(선택).")
    args = parser.parse_args(argv)

    try:
        records = load_all_content_records()
        metaphor = measure_metaphor_demand(records)
        slots = measure_slot_demand()
    except FileNotFoundError as exc:
        print(f"코퍼스 부재({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_MISSING

    if args.with_db:
        filled = measure_filled_slots()
        slots = SlotDemand(
            units=slots.units,
            ordered_total=slots.ordered_total,
            ordered_by_type=slots.ordered_by_type,
            conceptual_total=slots.conceptual_total,
            numeric_total=slots.numeric_total,
            filled_by_type=filled,
        )

    print(render_report(metaphor, slots))
    if args.json is not None:
        payload: dict[str, Any] = {
            "metaphor": {
                "total": metaphor.total,
                "blank": metaphor.blank,
                "ai_estimated": metaphor.ai_estimated,
                "defect_rows": metaphor.defect_rows,
                "defect_by_axis": metaphor.defect_by_axis,
                "gamified_rows": metaphor.gamified_rows,
            },
            "slots": {
                "units": slots.units,
                "ordered_total": slots.ordered_total,
                "ordered_by_type": slots.ordered_by_type,
                "conceptual_total": slots.conceptual_total,
                "numeric_total": slots.numeric_total,
                "filled_by_type": slots.filled_by_type,
            },
        }
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 리포트 저장: {args.json}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
