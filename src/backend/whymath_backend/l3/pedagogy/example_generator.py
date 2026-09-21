"""목표별 실생활 예시 생성기 — 정본: `docs/architecture/04e_pedagogy_strategy_catalog.md` §6.

`analogy_generator.py`(개념-grain 비유)의 *목표-grain* 짝이다. 04e §6.1 정본 좌석 선언:
**목표별 예시·보조 재료 = `pedagogy_content_slot`**(DRAFT→prescreen→review 상태기계 **재사용**),
소비처 = 발주서(`required_slots`) 잔여 슬롯. 여기는 grain이 목표(objective_id)라 슬롯 테이블을
*그대로* 쓴다 — 기존 `ContentSlotStore`(적재)·`PrescreenStore`/`ReviewStore`(전이)가 무수정
재사용되고, 새 상태기계·새 테이블은 만들지 않는다(acceptance 계약).

`slot_generator.py`의 결정론 픽스처가 "LLM 생성 경로는 소비처가 생길 때 도입(deferred)"이라
연기해 둔 그 경로의 해제다 — 소비처: 발주서의 잔여 *개념형* 슬롯(example_pair·contrast_case 등
`NUMERIC_SLOT_TYPES` 밖 유형). 숫자형(문제·답) 슬롯은 SymPy 검증 재료가 필요한 *문제 저작*이라
동등문제 생성기(`l3/equivalent/llm_generator.py`) 계열의 소관으로 남긴다(정직한 분담 —
이 생성기는 검증 불가능한 답을 지어내지 않는다).

교수학 제약(04e §6.4·프롬프트 강제): 실생활 예시는 **스토리텔링 서술 형식**(독립 유형 아님)·
게임형 금지·정답 유출 금지·학년 레지스터는 파라미터(독립 생성기 금지)·자작(저작권).

LLM 경로는 `analogy_generator`와 동일 선례(라우터 경유·provider 주입 seam·GENERAL 저작 스왑·
실패 None 폴백). **라이브 채움 실행은 Phaiakes9 런북 소관**(이 컨테이너에 로컬 LLM 없음 —
정직한 공백). provenance_id는 None으로 낸다 — LLM 생성분의 `content_provenance` 행 결선은
라이브 채움 런북에서 provenance 삽입과 함께 배선한다(여기서 지어내지 않음·payload에 생성기
각인만 남긴다).

7계층: L3 콘텐츠 생성. 슬롯 파이프라인(생성·예심·검수)·라우터를 재사용한다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from whymath_backend.config import Settings
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import ModelFamily
from whymath_backend.l3.pedagogy.analogy_checker import check_example_defects
from whymath_backend.l3.pedagogy.analogy_generator import AnalogyGenerator, _extract_json
from whymath_backend.l3.pedagogy.review import ReviewVerdict, review_slot
from whymath_backend.l3.pedagogy.slot_generator import (
    NUMERIC_SLOT_TYPES,
    _is_tts_safe,
    verify_slot_payload,
)

_LOGGER = logging.getLogger(__name__)

# 생성기 각인 — 슬롯 payload에 남기는 생성 경로 표식(버전 포함·REVIEWER_TAG 동형 철학).
EXAMPLE_GENERATOR_TAG: Final[str] = "llm:example_generator/v0.1"

# 학년 레지스터 허용값 — analogy_generator와 동일 축(파라미터·독립 생성기 금지).
_REGISTERS: Final[frozenset[str]] = frozenset({"초등", "중학", "고등", "대학"})


# ──────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 — 실생활 예시 교수학 제약(04e §6·스토리텔링은 서술 형식)
# ──────────────────────────────────────────────────────────────────────────
EXAMPLE_SYSTEM_PROMPT: Final[
    str
] = """당신은 WhyMath의 **실생활 예시 저작자**입니다. 주어진 학습목표 1개에 대해 그 목표의
사고 행동을 실생활 맥락에서 만나게 하는 예시 1편을 지어 JSON 하나로만 출력하세요.

## 좋은 실생활 예시의 기준
- **스토리텔링 서술**로 쓰세요 — 학생이 자기 일상에서 마주칠 법한 짧은 상황 이야기 안에
  목표 개념이 *자연스럽게* 작동해야 합니다(개념 이름을 나열하는 설명문 금지).
- 표면 장식이 아니라 **목표의 사고 행동이 실제로 필요해지는 상황**을 고르세요.
- 지시된 학년 레지스터(초등/중학/고등/대학)의 언어 수준·소재로 쓰세요.

## 절대 금기
- **정답을 흘리지 마세요** — 예시는 상황 제시까지이며, 결론 값을 본문에 쓰지 않습니다.
- **게임형 산출 금지** — 레벨업·퀘스트·경험치·랭킹·보상 같은 게임화 메커닉을 넣지 마세요.
  (주사위·확률 게임 같은 *수학 소재*로서의 게임 상황은 허용됩니다 — 학습을 게임으로
  포장하는 것이 금지입니다.)
- 교과서·기출·타사 교재 문장을 복제하지 말고 순수 자작으로 쓰세요.
- 수식은 렌더러-중립 LaTeX($...$ 짝 맞춤)로 쓰세요.

## 출력 형식 — JSON 객체 하나만 (코드펜스·설명 없이)
{"body": "실생활 예시 본문(2~5문장·한국어)", "structure_tags": ["태그1", "태그2"]}
"""


# ──────────────────────────────────────────────────────────────────────────
# 표적 계획 — 발주서(required_slots) 잔여 슬롯만(select-vs-generate)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ExampleTarget:
    """예시 생성 표적 1건 — 발주서 잔여 슬롯의 (목표, 슬롯 유형, 필요 수) + 프롬프트 맥락."""

    objective_id: str
    slot_type: str  # 팩 소유 자유 문자열(enum 금지 — ORM docstring 계약)
    count: int  # 잔여 필요 수(발주 - 승인)
    statement: str  # 학습목표 진술(프롬프트 맥락 — Minimal context)
    register: str = "고등"

    def __post_init__(self) -> None:
        if self.register not in _REGISTERS:
            raise ValueError(f"학년 레지스터 위반: {self.register!r} — 허용 {sorted(_REGISTERS)}")
        if self.count < 1:
            raise ValueError(f"잔여 수요는 1 이상이어야 합니다(현재 {self.count}).")


def plan_remaining_slots(
    work_order: Sequence[Mapping[str, Any]],
    approved_counts: Mapping[tuple[str, str], int],
    *,
    statements: Mapping[str, str] | None = None,
    register: str = "고등",
) -> list[ExampleTarget]:
    """발주서 × 승인 현황 → 잔여 *개념형* 슬롯 표적 목록(select-vs-generate·순수).

    `work_order`는 컴파일러 발주서 `{objective_id, slot_type, count}` 리스트(unit_compiler ⑤),
    `approved_counts`는 `(objective_id, slot_type) → APPROVED 슬롯 수`(호출자가 DB에서 계수해
    주입 — 이 함수는 DB를 모른다·순수). 잔여 = 발주 count − 승인 수(0 이하는 표적 제외 —
    이미 충족된 슬롯의 사전 대량 생성 금지·04e §6.4).

    **숫자형 슬롯(`NUMERIC_SLOT_TYPES`)은 표적에서 제외**한다 — 문제·답 저작은 SymPy 검증
    재료가 필요해 동등문제 생성기 소관이다(모듈 docstring 분담). `statements`는 목표 id →
    목표 진술(프롬프트 맥락·없으면 id 사용).
    """
    targets: list[ExampleTarget] = []
    for item in work_order:
        objective_id = str(item["objective_id"])
        slot_type = str(item["slot_type"])
        if slot_type in NUMERIC_SLOT_TYPES:
            continue  # 숫자형은 동등문제 생성기 소관(검증 불가능한 답을 지어내지 않는다).
        ordered = int(item["count"])
        approved = int(approved_counts.get((objective_id, slot_type), 0))
        remaining = ordered - approved
        if remaining < 1:
            continue  # 충족 슬롯 — 발주 없음(사전 대량 생성 금지).
        statement = (statements or {}).get(objective_id, objective_id)
        targets.append(
            ExampleTarget(
                objective_id=objective_id,
                slot_type=slot_type,
                count=remaining,
                statement=statement,
                register=register,
            )
        )
    return targets


# ──────────────────────────────────────────────────────────────────────────
# LLM 생성기 — AnalogyGenerator 조성 재사용(라우팅·호출·관측 미러 대신 위임)
# ──────────────────────────────────────────────────────────────────────────
class ExampleGenerator:
    """목표-grain 실생활 예시 LLM 생성기 — 산출은 `pedagogy_content_slot` DRAFT 행.

    라우팅·provider 호출·관측은 `AnalogyGenerator`의 내부 경로를 *조성*으로 재사용한다
    (같은 라우터 경유·GENERAL 저작 스왑·지속 루프·never-break 관측 — 중복 구현 0). 시스템
    프롬프트와 산출 조립만 예시 grain으로 바꾼다.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        settings: Settings | None = None,
        trace: TraceSink | None = None,
        subscription: str = "free",
        temperature: float = 0.9,
        authoring_family: ModelFamily | None = ModelFamily.GENERAL,
    ) -> None:
        # 내부 엔진 재사용 — 라우팅 결정·_invoke·관측이 전부 동일 경로(비유와 예시는 프롬프트·
        # 조립만 다르다). 별도 클래스 상속 대신 조성(내부 위임)으로 결합을 최소화한다.
        self._engine = AnalogyGenerator(
            provider,
            settings=settings,
            trace=trace,
            subscription=subscription,
            temperature=temperature,
            authoring_family=authoring_family,
        )

    def generate_slot_row(self, target: ExampleTarget, index: int) -> dict[str, Any] | None:
        """표적 슬롯 1점의 DRAFT 슬롯 행 생성 — 실패 시 None(안전 폴백·크래시 금지).

        반환 행은 `build_slot_rows` 산출과 동형 키라 기존 `ContentSlotStore.seed`(멱등 upsert)·
        `PrescreenStore`/`ReviewStore`(전이)가 무수정으로 소비한다. id는
        `{objective_id}:{slot_type}:llm:{index}` — 파일럿 픽스처 id(`...:{i}`)와 충돌하지 않는
        네임스페이스다(LLM 생성분 구분·멱등 재실행 안정).
        """
        prompt = self._build_user_prompt(target)
        decision = self._engine._decide_routing()
        try:
            generated = self._engine._invoke(prompt, decision, system=EXAMPLE_SYSTEM_PROMPT)
        except Exception as exc:  # noqa: BLE001 — provider 장애 시 배치 크래시 금지·안전 폴백.
            _LOGGER.warning(
                "예시 생성 provider 호출 실패(%s) — None 폴백: %s", type(exc).__name__, exc
            )
            return None
        self._engine._record_trace(decision, generated.usage)
        data = _extract_json(generated.text)
        if data is None:
            _LOGGER.warning("예시 생성 응답 JSON 파싱 실패 — None 폴백.")
            return None
        body = data.get("body")
        if not isinstance(body, str) or not body.strip():
            _LOGGER.warning("예시 생성 응답 body 결측/무효 — None 폴백.")
            return None
        raw_tags = data.get("structure_tags")
        tags = (
            [str(t).strip() for t in raw_tags if isinstance(t, str) and str(t).strip()]
            if isinstance(raw_tags, list)
            else []
        )
        return build_example_slot_row(target, body.strip(), tags, index)

    def _build_user_prompt(self, target: ExampleTarget) -> str:
        """표적 1건의 사용자 프롬프트 — 목표 진술·슬롯 유형·레지스터만(Minimal context)."""
        return (
            f"학습목표: {target.statement}\n"
            f"슬롯 유형: {target.slot_type}\n"
            f"학년 레지스터: {target.register}\n"
            "위 목표의 실생활 예시 1편을 스토리텔링 서술로 지어 JSON 하나로만 출력하세요 — "
            "정답 값을 본문에 쓰지 마세요."
        )


def build_example_slot_row(
    target: ExampleTarget, body: str, structure_tags: Sequence[str], index: int
) -> dict[str, Any]:
    """예시 본문 → `pedagogy_content_slot` DRAFT 행(순수·결정론 — `build_slot_rows` 동형 키).

    `sympy_verified`는 `verify_slot_payload`에 위임한다 — 예시 payload에 `verification` 주장이
    없으므로 None(개념형 정직 표기)이 되며, 값이 있다면 실제 SymPy 판정을 거친다(검증 없는
    True 금지). `provenance_id=None` — LLM 생성분 provenance 결선은 라이브 채움 런북 소관
    (모듈 docstring 정직한 공백)이며, payload의 `generated_by` 각인이 경로를 남긴다.
    """
    tags = [str(t) for t in structure_tags] or [target.slot_type]
    payload: dict[str, Any] = {
        "body": body,
        "reasoning_type": target.slot_type,
        "structure_tags": tags,
        "register": target.register,
        "generated_by": EXAMPLE_GENERATOR_TAG,
    }
    return {
        "id": f"{target.objective_id}:{target.slot_type}:llm:{index}",
        "objective_id": target.objective_id,
        "slot_type": target.slot_type,
        "payload": payload,
        # EOS-89: payload에 `verification` 주장이 없으므로 능력 미주입이어도 None이 정상 반환된다
        # (주장이 생기면 LookupError — 그때 상류에서 `equivalence=`를 내려야 한다).
        "sympy_verified": verify_slot_payload(payload),
        "tts_safe": _is_tts_safe(payload),
        "provenance_id": None,
        "status": "DRAFT",
    }


def review_example_rows(rows: Sequence[dict[str, Any]]) -> list[tuple[str, ReviewVerdict]]:
    """예시 슬롯 행 검수 — 기존 `review_slot` 게이트 + 예시 결함 축(`check_example_defects`).

    `review_rows`(기존)의 예시 확장판이다: 구조+기호 게이트를 통과한 행에 한해 정답 유출·게임형
    축을 추가 검사하고, 걸리면 결함 코드를 반려 사유로 얹는다(fail-closed). 반환 형태는 기존
    `ReviewStore.apply` 입력과 동일해 상태 전이가 무수정 재사용된다 — **APPROVED 산출의 게임형
    0**은 이 게이트가 구조적으로 보장한다(acceptance "게임형 산출 0 검사"의 슬롯측 시행 지점).
    """
    verdicts: list[tuple[str, ReviewVerdict]] = []
    for row in rows:
        payload = row["payload"]
        # EOS-89: 예시 payload는 `verification` 주장을 담지 않으므로(`build_example_slot_row`)
        # 항등 판정 능력이 필요 없다 — 그래서 이 호출부는 합성 루트를 알 이유가 없다(pull 0 유지).
        # 주장이 있는 행이 흘러들면 `verify_slot_payload`가 LookupError로 크게 실패한다.
        verdict = review_slot(payload)
        if verdict.approved:
            answer = payload.get("answer")
            defects = check_example_defects(
                str(payload.get("body", "")),
                str(answer) if answer is not None else None,
            )
            if defects:
                verdict = ReviewVerdict(False, defects[0])
        verdicts.append((str(row["id"]), verdict))
    return verdicts


__all__ = [
    "EXAMPLE_GENERATOR_TAG",
    "EXAMPLE_SYSTEM_PROMPT",
    "ExampleTarget",
    "plan_remaining_slots",
    "ExampleGenerator",
    "build_example_slot_row",
    "review_example_rows",
]
