"""생성 단계 — 발주서(work_order)/slot_manifest → `pedagogy_content_slot` DRAFT 행.

PED-01 파일럿 E2E의 첫 중간 단계다. 컴파일러가 낸 슬롯 주문(목표별 `{type, count}`)을 받아
목표당 슬롯 유형별 `count`개의 콘텐츠 payload를 *결정론적으로* 만든다.

────────────────────────────────────────────────────────────────────────────
왜 결정론적 픽스처인가 (LLM 라우터 아님)
────────────────────────────────────────────────────────────────────────────
이 단계의 목적은 "스키마가 5단계를 지탱함을 1회 증명"하는 walking-skeleton이다. LLM 생성은
CI에서 self-skip(라이브 provider·Langfuse 필요)이라 E2E가 생성 단계를 실제로 못 밟는다. 그래서
파일럿은 결정론적 픽스처를 쓴다:
  - 숫자형 슬롯(문제·답이 있는 유형)은 SymPy(`identity_status`)로 답을 *실제로* 검증해
    `sympy_verified`를 정직하게 True/False로 채운다 — 검증 없는 신뢰 금지(CLAUDE.md).
  - 개념형 슬롯(수치 답이 없는 유형)은 `sympy_verified=None`(컬럼이 nullable인 이유)으로 둔다.
자체 저작이라 `provenance_id=None`(ORM docstring이 사람 저작에 허용). LLM 생성 경로는 실제
콘텐츠 파이프라인이 소비처가 될 때 도입한다(소비처 0 추상 금기 회피) — deferred.

7계층: L3 콘텐츠 생성. 컴파일러(L1) 산출물 소비·SymPy 동치(L3 `symbolic_equivalence`)·sync 엔진
빌더(L1 `build_sync_engine`)를 재사용한다(신규 seam 최소·`UnitSpecStore` 미러).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

# EOS-69: Core는 **좁은 능력 계약**(schema.verification_capabilities)만 안다.
# EOS-89: 나아가 구현을 합성 루트에서 **끌어오지도 않는다**(계획서 100 §3.8 "등록 형태").
# 능력은 상류가 주입하며, 판정이 필요한데 주입이 없으면 조용히 넘어가지 않고 터진다
# (`_require_equivalence`) — 미검증을 "검증 통과"로 위장하는 폴백을 두지 않기 위해서다.
# `SubjectAdapter` 필수 3종에 넣지 않은 이유는 계약 모듈 docstring 참조(항등 판정은 역사·국어엔
# 없다 — 필수로 만들면 빈 구현을 강요한다).
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.pedagogy_dsl import PedagogyContentSlot
from whymath_backend.l1.embedding_primitives import build_sync_engine
from whymath_backend.schema.verification_capabilities import (
    EquivalenceOutcome,
    ExpressionEquivalence,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


# ──────────────────────────────────────────────────────────────────────────
# 슬롯 유형 분류 — 숫자형(SymPy 검증 대상) vs 개념형(검증 미대상)
# ──────────────────────────────────────────────────────────────────────────
# 문제·답이 있어 SymPy로 결정 가능한 유형. 파일럿 4팩(CONCEPT/PROCEDURE/REPRESENT/MODELING)이
# 쓰는 슬롯 유형 중 수치 답을 갖는 것들. 나머지(개념형)는 sympy_verified를 None으로 둔다.
NUMERIC_SLOT_TYPES: frozenset[str] = frozenset(
    {
        "worked_example",
        "completion_problem",
        "solo_problem",
        "diag_item",
        "problem_variation",
        "error_analysis",
        "polya_worked",
    }
)


# ──────────────────────────────────────────────────────────────────────────
# payload 검증 — 숫자형 슬롯의 답을 SymPy로 실제 대조
# ──────────────────────────────────────────────────────────────────────────
def _require_equivalence(equivalence: ExpressionEquivalence | None) -> ExpressionEquivalence:
    """항등 판정 능력이 실제로 필요한 순간에만 존재를 강제한다 — 없으면 즉시 `LookupError`.

    왜 "선택 인자 + 필요 시 예외"인가(EOS-89): 이 모듈의 두 하류 호출부
    (`example_generator`·`diag_item_projector`)가 만드는 payload에는 `verification` 주장이
    **구조적으로 없다** — 그들에게 능력을 필수 인자로 요구하면, 쓰지도 않을 능력을 얻기 위해
    합성 루트를 import하게 되고 그 순간 pull 지점이 새로 생긴다(이 태스크가 없앤 것).

    반대로 기본값 폴백(`default_expression_equivalence()`)을 두면 미주입이 조용히 통과하고,
    그 폴백 한 줄이 Core → 합성 루트 간선을 되살린다. 그래서 **필요할 때만, 크게 실패한다**.
    """
    if equivalence is None:
        raise LookupError(
            "항등 판정(ExpressionEquivalence) 능력이 주입되지 않았습니다 — "
            "`verification` 주장이 있는 payload는 과목 능력 없이 판정할 수 없습니다. "
            "상류에서 `equivalence=`로 주입하십시오(app.state 등록분 또는 합성 루트)."
        )
    return equivalence


def verify_slot_payload(
    payload: dict[str, Any], *, equivalence: ExpressionEquivalence | None = None
) -> bool | None:
    """payload에 `verification`(claim_lhs≡claim_rhs 주장)이 있으면 판정, 없으면 None.

    반환:
      - True: `identity_status(claim_lhs, claim_rhs) == identity`(답이 실제로 맞음).
      - False: not_identity/undecidable/parse_error(답이 틀렸거나 검증 불가 — **fail-closed**).
      - None: `verification` 키 없음(개념형 슬롯 — 수치 검증 대상 아님).

    검증 없는 True 표기 금지 — 실제 판정을 거쳐야만 sympy_verified가 True가 된다.

    `equivalence`는 과목의 항등 판정 능력(EOS-69·EOS-89). `verification` 주장이 **있는데**
    주입이 없으면 `LookupError`다(`_require_equivalence` docstring — 조용한 폴백 금지).
    주장이 없으면 능력을 아예 건드리지 않으므로 미주입이어도 None이 정상 반환된다.
    4상태 중 `identity`만 True이고 나머지 3종은 전부 False다(기존과 동일 — `undecidable`을
    True로 올리지 않는다).
    """
    verification = payload.get("verification")
    if not verification:
        return None
    lhs = str(verification.get("claim_lhs", ""))
    rhs = str(verification.get("claim_rhs", ""))
    verifier = _require_equivalence(equivalence)
    return verifier.identity_status(lhs, rhs) is EquivalenceOutcome.identity


def _is_tts_safe(payload: dict[str, Any]) -> bool:
    """TTS 안전성 구조 검사 — 본문(body)이 비어있지 않고 수식 구분자($)가 짝을 이루는가.

    짝이 안 맞는 `$`는 TTS 분절을 깨뜨린다(수식/일반텍스트 경계 붕괴). walking-skeleton 수준의
    *변별 가능한* 최소 검사다 — 성공/실패 양쪽에서 다른 값을 낸다(빈 본문·홀수 개 $ → False).
    """
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        return False
    return body.count("$") % 2 == 0


# ──────────────────────────────────────────────────────────────────────────
# payload 빌더 — 슬롯 유형별 결정론적 콘텐츠(index로 변주)
# ──────────────────────────────────────────────────────────────────────────
def _build_numeric_payload(slot_type: str, objective_id: str, index: int) -> dict[str, Any]:
    """숫자형 슬롯 payload — 이차함수 최솟값 문제(index로 상수항 변주·답 SymPy 검증 가능).

    f(x) = x^2 - 4x + c (c = 3 + index) → 꼭짓점 x=2 · 최솟값 = c - 4 = index - 1.
    `verification`이 담은 주장 `(2)**2 - 4*(2) + c ≡ (index-1)`을 `verify_slot_payload`가 실제
    SymPy로 대조한다(답을 일부러 틀리게 넣으면 not_identity로 잡힌다).
    """
    c = 3 + index
    answer = index - 1
    return {
        "body": f"이차함수 $f(x) = x^{{2}} - 4x + {c}$ 의 최솟값을 구하시오.",
        "answer": str(answer),
        "reasoning_type": slot_type,
        "structure_tags": ["quadratic", "extremum"],
        # SymPy 검증 재료 — 렌더 대상 아님(검산용 구조·표현≠의미).
        "verification": {
            "claim_lhs": f"(2)**2 - 4*(2) + {c}",
            "claim_rhs": str(answer),
        },
    }


def _build_conceptual_payload(slot_type: str, objective_id: str, index: int) -> dict[str, Any]:
    """개념형 슬롯 payload — 수치 답이 없는 사고 유도 본문(SymPy 검증 미대상).

    슬롯 유형을 reasoning_type로 명시하고, 렌더러-중립 LaTeX 본문을 담는다. `verification` 키가
    없으므로 `verify_slot_payload`가 None을 반환 → sympy_verified는 None으로 정직하게 남는다.
    """
    return {
        "body": (
            f"이차함수 $y = x^{{2}}$ 를 소재로, 이 슬롯(유형 {slot_type})의 사고 행동을 "
            f"학생이 스스로 수행하도록 유도하는 발문 {index + 1}."
        ),
        "reasoning_type": slot_type,
        "structure_tags": ["quadratic", "conceptual"],
    }


def build_slot_rows(
    objective_id: str,
    slot_manifest: Sequence[dict[str, Any]],
    *,
    equivalence: ExpressionEquivalence | None = None,
) -> list[dict[str, Any]]:
    """목표 1개의 slot_manifest(list[{type,count}]) → `pedagogy_content_slot` 행 dict 리스트.

    각 슬롯 유형마다 `count`개의 payload를 결정론적으로 만든다
    (id = `{objective_id}:{slot_type}:{i}`).
    숫자형 유형은 SymPy로 답을 검증해 `sympy_verified`를 채우고, 개념형은 None으로 둔다. 모든 행은
    fail-closed로 `status='DRAFT'`·`provenance_id=None`(자체 저작)으로 낸다.

    `slot_manifest`에 숫자형 유형이 하나라도 있으면 `equivalence`(과목 항등 판정)가 **필요하다** —
    없으면 `verify_slot_payload`가 `LookupError`를 던진다(EOS-89 · 조용한 미검증 금지).
    """
    rows: list[dict[str, Any]] = []
    for slot in slot_manifest:
        slot_type = str(slot["type"])
        count = int(slot["count"])
        is_numeric = slot_type in NUMERIC_SLOT_TYPES
        for i in range(count):
            payload = (
                _build_numeric_payload(slot_type, objective_id, i)
                if is_numeric
                else _build_conceptual_payload(slot_type, objective_id, i)
            )
            rows.append(
                {
                    "id": f"{objective_id}:{slot_type}:{i}",
                    "objective_id": objective_id,
                    "slot_type": slot_type,
                    "payload": payload,
                    # 실제 SymPy 판정을 거친 값만 True가 된다(개념형은 None).
                    "sympy_verified": verify_slot_payload(payload, equivalence=equivalence),
                    "tts_safe": _is_tts_safe(payload),
                    "provenance_id": None,
                    "status": "DRAFT",
                }
            )
    return rows


# ──────────────────────────────────────────────────────────────────────────
# 시더: ContentSlotStore (멱등 upsert — UnitSpecStore 미러)
# ──────────────────────────────────────────────────────────────────────────
class ContentSlotStore:
    """생성 산출물(슬롯 행) → `pedagogy_content_slot` 멱등 적재기(`UnitSpecStore` 미러).

    한 `engine.begin()` 안에서 각 행을 `id` 충돌 upsert한다(PK `id`는 SET에서 제외해 보존·멱등).
    sync 엔진은 슬3 `build_sync_engine`을 재사용한다(신규 seam 0).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = build_sync_engine(self._resolved_settings)
        return self._engine

    def seed(self, rows: Sequence[dict[str, Any]]) -> int:
        """슬롯 행들을 `id` 충돌 upsert. 반환=적재 행 수.

        각 행 dict의 키만 바인딩하고 PK `id`는 SET에서 뺀다(멱등).
        JSONB payload는 dict 그대로 실린다.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        with self._get_engine().begin() as conn:
            for row in rows:
                update_keys = set(row) - {"id"}
                stmt = pg_insert(PedagogyContentSlot).values(**row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[PedagogyContentSlot.id],
                    set_={key: stmt.excluded[key] for key in update_keys},
                )
                conn.execute(stmt)
        return len(rows)


__all__ = [
    "NUMERIC_SLOT_TYPES",
    "verify_slot_payload",
    "build_slot_rows",
    "ContentSlotStore",
]
