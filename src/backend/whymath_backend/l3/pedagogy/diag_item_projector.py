"""형성평가 `diag_item` 슬롯 채움 — 정본: `04e_pedagogy_strategy_catalog.md` §7.2(PED-10).

04e §7.2가 명시한 원천을 그대로 쓴다: **생성이 아니라 투영**이다. `atom_probe` 전량(원자 code 키
②진단문항 — 발문 `diagnostic_item`·통과기준 `diagnostic_answer`·오답신호 `diagnostic_signal`)을
목표(objective_id) grain의 `pedagogy_content_slot(slot_type='diag_item')`으로 투영한다. LLM 호출
없음(검증된 기존 자산 재사용 — `analogy_generator`/`example_generator`와 달리 라우터 경유 불필요).

────────────────────────────────────────────────────────────────────────────
grain 다리 — 04e §7.2 설계의 실측 정정 (crosswalk 불필요)
────────────────────────────────────────────────────────────────────────────
04e §7.2는 "개념↔원자 crosswalk 경유"를 그리지만, 실측하면 그 다리가 이미 다른 곳에서 닫혀 있다.
`learning_objective.concept_nodes`는 H2 계약(`db/models/pedagogy_dsl.py`)상 **원자 백본(atom_node)
code 배열 그 자체**이며(legacy 437/545 개념 그래프가 아니다), `l1/pedagogy/unit_compiler.py`가
컴파일 시점에 `obj.concept_nodes`를 `valid_atom_codes`(원자 백본 전량)에 대조 검증한다 — 즉 저작
단계에서 이미 원자 code로 쓰인다. `atom_probe.code`도 같은 원자 세부개념 code 공간(K-12·대학 겹침
0)이므로, 목표→원자의 다리는 **`concept_nodes`와 `atom_probe.code`의 직접 교집합**이다.
`data/corpus/concept_atom_crosswalk_v1`(구 437-개념-id ↔ 원자 code)는 다른 소비처(예: 구 개념 그래프
축의 콘텐츠 이관) 용이지 이 bridging에는 쓰이지 않는다 — 존재하지 않는 다리를 새로 놓지 않는다
(04e §3.2의 "유령 참조 재사용 금지" G7과 동일 원칙).

────────────────────────────────────────────────────────────────────────────
select-vs-generate — 이미 검수된 슬롯은 손대지 않는다
────────────────────────────────────────────────────────────────────────────
`ContentSlotStore.seed()`는 상태 가드 없이 전 컬럼을 upsert한다(멱등 PK 충돌만 방지). 그래서 이
모듈의 오케스트레이터가 *호출 전에* 대상 슬롯 id의 현재 status를 조회해 `DRAFT`(또는 미존재)인
것만 표적으로 남긴다 — `PRESCREENED`/`APPROVED`/`REJECTED`로 이미 전이된 슬롯은 표적에서 제외한다
(사람 검수 결정을 재적재로 덮어쓰지 않는다).

────────────────────────────────────────────────────────────────────────────
판정치 규약 — 표본 0은 0%가 아니라 None
────────────────────────────────────────────────────────────────────────────
`DiagItemFillReport.prescreen_pass_rate`는 채움 0건이면 `None`이다(`EffectivenessStat` 선례와
동일 축 — 측정 안 됨과 성과 0%를 같은 값으로 위장하지 않는다).

7계층: L3 콘텐츠 생성. `atom_probe`·`learning_objective`(L1 영속)를 조회만 하고(L_n→L_{n-1}
허용), 기존 슬롯 파이프라인(`slot_generator`/`prescreen`)을 무수정 재사용한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from whymath_backend.config import Settings, get_settings
from whymath_backend.l1.embedding_primitives import build_sync_engine
from whymath_backend.l3.pedagogy.prescreen import (
    PRESCREEN_PASS_THRESHOLD,
    PrescreenStore,
    prescreen_rows,
)
from whymath_backend.l3.pedagogy.slot_generator import (
    ContentSlotStore,
    _is_tts_safe,
    verify_slot_payload,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# 투영기 각인 — 슬롯 payload에 남기는 산출 경로 표식(EXAMPLE_GENERATOR_TAG 동형 철학).
DIAG_ITEM_PROJECTOR_TAG: Final[str] = "projection:atom_probe/v0.1"

_SLOT_TYPE: Final[str] = "diag_item"

# `PedagogyContentSlot.status` 중 "이미 사람 결정이 개입한" 상태 — 재적재 금지 대상.
_NON_DRAFT_STATUSES: Final[frozenset[str]] = frozenset({"PRESCREENED", "APPROVED", "REJECTED"})


# ──────────────────────────────────────────────────────────────────────────
# 표적 계획 — 순수(DB 비의존)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DiagItemTarget:
    """진단문항 슬롯 표적 1건 — (목표, 원자, 슬롯 id) + atom_probe 3필드."""

    objective_id: str
    slot_id: str
    atom_code: str
    stem: str
    answer: str | None
    signal: str | None


def diag_item_count(slot_manifest: Sequence[Mapping[str, Any]]) -> int:
    """`slot_manifest`(목표별 `[{type,count}]`)에서 `diag_item` 발주 수를 뽑는다.

    `_merge_slots`(unit_compiler)가 유형별로 dedup해 만드므로 보통 항목 1개지만, 방어적으로
    합산한다(중복이 있어도 발주 총량을 놓치지 않는다).
    """
    return sum(int(item["count"]) for item in slot_manifest if item.get("type") == _SLOT_TYPE)


def plan_diag_item_targets(
    objectives: Sequence[Mapping[str, Any]],
    existing_status_by_id: Mapping[str, str],
    probes_by_code: Mapping[str, Mapping[str, str | None]],
) -> list[DiagItemTarget]:
    """objectives × 기존 슬롯 status × atom_probe 후보 → 표적 목록(select-vs-generate·순수).

    `objectives`는 `[{objective_id, concept_nodes: [atom_code,...], slot_manifest: [...]}]`.
    `existing_status_by_id`는 `{slot_id: status}`(호출자가 DB에서 조회해 주입 — 이 함수는 DB를
    모른다). `probes_by_code`는 `{atom_code: {"stem":..., "answer":..., "signal":...}}` — `stem`이
    없는(공백) 원자는 애초에 이 매핑에 넣지 않는다(호출자 책임).

    슬롯 id는 기존 컨벤션 `{objective_id}:diag_item:{i}`(파일럿 `build_slot_rows`와 동일
    네임스페이스 — 같은 id를 upsert로 갱신하는 것이 의도다: 워킹 스켈레톤 픽스처를 실제
    atom_probe 콘텐츠로 교체). `i`는 발주 수(`diag_item_count`) 범위 안에서 0부터 순서대로 매기되,
    **이미 사람 결정이
    개입한 슬롯(PRESCREENED/APPROVED/REJECTED)은 건너뛰고 그 자리의 원자 후보도 소비하지 않는다**
    (그 슬롯은 이미 별도 콘텐츠로 채워진 것으로 본다). 후보(원자 code)는 `concept_nodes` 순서대로
    소진하며, 남은 DRAFT 슬롯 수보다 후보가 적으면 **부분 채움**으로 정직하게 끝난다(사전 대량
    생성 금지·04e §6.4와 동일 원칙).
    """
    targets: list[DiagItemTarget] = []
    for obj in objectives:
        objective_id = str(obj["objective_id"])
        count = diag_item_count(obj.get("slot_manifest") or [])
        if count < 1:
            continue
        candidates = [code for code in obj.get("concept_nodes") or [] if code in probes_by_code]
        candidate_idx = 0
        for i in range(count):
            slot_id = f"{objective_id}:{_SLOT_TYPE}:{i}"
            if existing_status_by_id.get(slot_id) in _NON_DRAFT_STATUSES:
                continue  # 이미 검수 결정이 난 슬롯 — 손대지 않는다(원자 후보도 소비하지 않음).
            if candidate_idx >= len(candidates):
                break  # 남은 원자 후보 소진 — 부분 채움으로 정직하게 끝난다.
            atom_code = candidates[candidate_idx]
            candidate_idx += 1
            probe = probes_by_code[atom_code]
            targets.append(
                DiagItemTarget(
                    objective_id=objective_id,
                    slot_id=slot_id,
                    atom_code=atom_code,
                    stem=str(probe["stem"]),
                    answer=probe.get("answer"),
                    signal=probe.get("signal"),
                )
            )
    return targets


def build_diag_item_slot_row(target: DiagItemTarget) -> dict[str, Any]:
    """표적 1건 → `pedagogy_content_slot` DRAFT 행(순수·결정론 — `build_slot_rows` 동형 키).

    `answer`/`signal`은 atom_probe 원본이 nullable이라 없으면 payload에 키 자체를 넣지 않는다
    (있지도 않은 값을 빈 문자열로 지어내지 않는다). `verification` 주장을 넣지 않으므로
    `verify_slot_payload`는 None(개념형 정직 표기) — atom_probe의 통과기준은 자유서술이라
    SymPy로 결정 가능한 등식 주장이 아니다(검증 없는 True 금지).
    """
    payload: dict[str, Any] = {
        "body": target.stem,
        "reasoning_type": _SLOT_TYPE,
        "structure_tags": ["atom_probe", "formative_assessment"],
        "atom_code": target.atom_code,
        "generated_by": DIAG_ITEM_PROJECTOR_TAG,
    }
    if target.answer is not None:
        payload["answer"] = target.answer
    if target.signal is not None:
        payload["signal"] = target.signal
    return {
        "id": target.slot_id,
        "objective_id": target.objective_id,
        "slot_type": _SLOT_TYPE,
        "payload": payload,
        # EOS-89: atom_probe payload에는 `verification` 주장이 없다 — 능력 미주입이어도 None.
        # 이 호출부가 합성 루트를 import하지 않는 이유이기도 하다(pull 지점 0 유지).
        "sympy_verified": verify_slot_payload(payload),
        "tts_safe": _is_tts_safe(payload),
        "provenance_id": None,
        "status": "DRAFT",
    }


# ──────────────────────────────────────────────────────────────────────────
# 보고 — 표본 0은 None(0% 위장 금지·EffectivenessStat 동형)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class DiagItemFillReport:
    """채움 결과 — 채움 건수·prescreen 통과율(PED-10 acceptance ②)."""

    filled: int = 0
    prescreen_passed: int = 0

    @property
    def prescreen_pass_rate(self) -> float | None:
        if self.filled == 0:
            return None
        return self.prescreen_passed / self.filled

    def to_json(self) -> dict[str, Any]:
        return {
            "filled": self.filled,
            "prescreen_passed": self.prescreen_passed,
            "prescreen_pass_rate": self.prescreen_pass_rate,
        }


def project_diag_item_slots(
    objectives: Sequence[Mapping[str, Any]],
    existing_status_by_id: Mapping[str, str],
    probes_by_code: Mapping[str, Mapping[str, str | None]],
) -> tuple[list[dict[str, Any]], list[tuple[str, int]], DiagItemFillReport]:
    """계획→행 빌드→예심 채점까지 순수 파이프라인(DB IO 없음 — `prescreen_rows`도 순수).

    반환된 `rows`/`scored`를 호출자가 각각 `ContentSlotStore.seed()`(적재)·
    `PrescreenStore.apply(scored)`(전이)에 넘겨야 실제로 영속된다 — 이 함수 자체는 아무것도
    쓰지 않는다(오케스트레이터가 IO 담당). `scored`를 여기서 한 번만 계산해 호출자가 다시
    `prescreen_rows`를 돌리지 않게 한다(같은 순수 계산 중복 방지).
    """
    targets = plan_diag_item_targets(objectives, existing_status_by_id, probes_by_code)
    rows = [build_diag_item_slot_row(t) for t in targets]
    if not rows:
        return rows, [], DiagItemFillReport()
    scored = prescreen_rows(rows)
    passed = sum(1 for _, score in scored if score >= PRESCREEN_PASS_THRESHOLD)
    return rows, scored, DiagItemFillReport(filled=len(rows), prescreen_passed=passed)


# ──────────────────────────────────────────────────────────────────────────
# DB 조회 — sync 엔진(ContentSlotStore/PrescreenStore와 동일 좌석)
# ──────────────────────────────────────────────────────────────────────────
def _load_objectives(engine: Engine) -> list[dict[str, Any]]:
    """`learning_objective`(id·concept_nodes·slot_manifest) 전량 조회."""
    from sqlalchemy import select

    from whymath_backend.db.models.pedagogy_dsl import LearningObjective

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                LearningObjective.id,
                LearningObjective.concept_nodes,
                LearningObjective.slot_manifest,
            )
        ).all()
    return [
        {"objective_id": r.id, "concept_nodes": r.concept_nodes, "slot_manifest": r.slot_manifest}
        for r in rows
    ]


def _load_probes_by_code(
    engine: Engine, atom_codes: Sequence[str]
) -> dict[str, dict[str, str | None]]:
    """`atom_probe`에서 발문(`diagnostic_item`)이 있는 원자만 code→3필드 매핑으로 조회.

    빈 `atom_codes`는 쿼리하지 않고 빈 dict를 돌려준다(불필요한 왕복 회피).
    """
    if not atom_codes:
        return {}
    from sqlalchemy import select

    from whymath_backend.db.models.atom_probe import AtomProbe

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                AtomProbe.code,
                AtomProbe.diagnostic_item,
                AtomProbe.diagnostic_answer,
                AtomProbe.diagnostic_signal,
            ).where(
                AtomProbe.code.in_(set(atom_codes)),
                AtomProbe.diagnostic_item.is_not(None),
            )
        ).all()
    return {
        r.code: {
            "stem": r.diagnostic_item,
            "answer": r.diagnostic_answer,
            "signal": r.diagnostic_signal,
        }
        for r in rows
        if r.diagnostic_item and r.diagnostic_item.strip()
    }


def _load_existing_status(engine: Engine, slot_ids: Sequence[str]) -> dict[str, str]:
    """대상 슬롯 id 후보의 현재 status 조회(select-vs-generate 가드 재료).

    빈 `slot_ids`는 쿼리하지 않는다.
    """
    if not slot_ids:
        return {}
    from sqlalchemy import select

    from whymath_backend.db.models.pedagogy_dsl import PedagogyContentSlot

    with engine.connect() as conn:
        rows = conn.execute(
            select(PedagogyContentSlot.id, PedagogyContentSlot.status).where(
                PedagogyContentSlot.id.in_(set(slot_ids))
            )
        ).all()
    return {r.id: r.status for r in rows}


def run_diag_item_fill(
    *, engine: Engine | None = None, settings: Settings | None = None
) -> DiagItemFillReport:
    """전체 파이프라인 오케스트레이션 — DB 조회 → 계획 → 적재 → 예심 → 보고.

    조회 2단계: ①목표 전량 + atom code 후보 수집 ②그 후보들의 atom_probe·기존 슬롯 status를
    후보 범위로만 조회(전량 스캔 회피). 채움 0건이면 seed/prescreen 호출 자체를 생략한다(빈 배치
    upsert는 무해하지만 불필요한 트랜잭션을 열지 않는다).
    """
    eng = engine or build_sync_engine(settings or get_settings())
    objectives = _load_objectives(eng)
    all_atom_codes = {code for obj in objectives for code in (obj["concept_nodes"] or [])}
    probes_by_code = _load_probes_by_code(eng, sorted(all_atom_codes))

    candidate_slot_ids = [
        f"{obj['objective_id']}:{_SLOT_TYPE}:{i}"
        for obj in objectives
        for i in range(diag_item_count(obj["slot_manifest"] or []))
    ]
    existing_status_by_id = _load_existing_status(eng, candidate_slot_ids)

    rows, scored, report = project_diag_item_slots(
        objectives, existing_status_by_id, probes_by_code
    )
    if rows:
        ContentSlotStore(engine=eng).seed(rows)
        PrescreenStore(engine=eng).apply(scored)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입 — `run_diag_item_fill` 실행 + 채움 건수·prescreen 통과율 보고.

    라이브 실행은 실 Postgres가 필요하다(이 컨테이너에는 없음 — 정직한 공백. Phaiakes9
    런북 소관, `analogy_generator`/`example_generator`의 동일 공백 선례). 경로 결선·실행·보고만
    한다(적재 로직 0 — `l1/atom_probe/populate.py` CLI 골격과 동형).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="whymath-diag-item-fill",
        description="atom_probe ②진단문항 → pedagogy_content_slot(diag_item) 투영 채움.",
    )
    parser.parse_args(argv)

    report = run_diag_item_fill()
    print(
        f"diag_item 슬롯 채움: {report.filled}건 "
        f"(prescreen 통과율={report.prescreen_pass_rate!r})."
    )
    return 0


__all__ = [
    "DIAG_ITEM_PROJECTOR_TAG",
    "DiagItemTarget",
    "DiagItemFillReport",
    "diag_item_count",
    "plan_diag_item_targets",
    "build_diag_item_slot_row",
    "project_diag_item_slots",
    "run_diag_item_fill",
    "main",
]

if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
