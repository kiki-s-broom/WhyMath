"""CU 사후 LLM 힌트 패스 — 저장된 동등문제 CU에 단계 목록 + L1·L2·L3 힌트를 붙인다 (EOS-211).

왜 이 모듈이 있는가
------------------
CU 정의(`docs/standards/eos_verification_design_v1.md` §3)는 "문제 지문 + 정답 + 단계별 풀이 +
**3단계 힌트** + …"다. 그런데 동등문제 생성기(`l3/equivalent`)가 만든 CU에는 지문·정답·해설 문장
(`answer_explanation`)·검산식(`verify`)만 있고 단계별 풀이·힌트가 없다(EOS-197 A6 회차 30 CU 전부
힌트 0건). 기존 힌트 생성기(`generator.py`)는 **LLM 0 템플릿** 방식이라 검증된 풀이 단계
(`sympy_verified`)가 있어야 동작하므로 CU에는 쓸 수 없다. 그래서 G3 조건 "힌트 의미 누설 0"이
측정 대상 부재였다(EOS-207 첫 측정).

Kiki 결정(2026-10-29) "사후 LLM 힌트 패스": 이미 저장된 CU에 LLM이 단계 목록과 L1·L2·L3 힌트를
붙이고, **게이트 3종(`gates.evaluate_gates`)을 통과한 것만 verified=true**로 둔다.

흐름(CU 1건)
-----------
  CU 로드 → 라우터 결정(`Router().route`) → provider.generate(라우터 결정 동봉)
  → 생성 로그 1행 즉시 기록 → JSON 파싱·스키마 검증 → 실패면 재시도(기본 2회)
  → 성공이면 Hint 3건 조립 → 게이트 3종 → 통과분 `cu.hints.jsonl` · 거부분
  `cu.hints.rejected.jsonl` → 문맥(단계·개념) `cu.hints.context.jsonl`.

LLM은 L3 라우터 경유로만 부른다(CLAUDE.md "LLM 호출은 항상 라우터 경유"). provider는 **주입**받는다
— 표준 조립(`CompositeProvider(Ollama + build_cloud_provider())`)은 프로세스 시작점
`harness/cu_hint_pass.py`가 한다. 좌석 선택은 저작 경로와 같은 라우팅 신호다(EOS-197 회차 방식):
  - 로컬 좌석: 구독·예산 미지정(=free·0) → 라우터 규칙 1·2가 LOCAL 강제 → 비동기 신호(`sync=False`)
    + `task_type="generate"`라 축2 규칙 2가 **QUALITY**를 고른다(EOS-197
    `--authoring-tier quality`와 같은 좌석 — 모델 ID를 여기 박지 않는다, 선택은 라우터 몫이고
    실제 모델은 생성 로그에 남는다).
  - 클라우드 좌석: `--subscription premium --budget-krw 5000`(둘이 함께여야 클라우드) → 축1 규칙 4가
    CLOUD_MID → 좌석은 `settings.cloud_provider`가 정한다(`build_cloud_provider`).
  난이도 신호는 문항 난이도가 아니라 **힌트 저작 과업의 난이도**라 `medium`으로 고정한다 — 문항
  난이도를 그대로 쓰면 `killer` 문항에서 CLOUD_HIGH(단가 미등재 핀)로 튄다.

결정론 합성 ID 규칙 (CU에는 실제 풀이 경로가 없다)
-----------------------------------------------
  - `solution_path_id = "cu-" + <CU slug>` (예 `cu-wm-gen-calc1-443f1ed59b71`). 실제 경로 ID 체계
    (`sp-{verified_solutions.id}` — `whs/path_promotion`·`l3/multi_solution`)와 평가 하네스
    (`aq-eval-…`)와 접두가 겹치지 않는다. slug는 CU의 안정 키(멱등 upsert 키)라 재실행에 불변이다.
  - `step_order = 1` 고정 — 세 힌트 모두 "풀이를 시작하는 자리(첫 단계)"를 겨냥한다. L3는 첫 단계만
    시연하고(마지막 단계 시연 = 전체 풀이 = Level 4, 엔티티 밖), 그래서 단계는 2개 이상이어야 한다.
  - `hint_id = hint_id_for(solution_path_id, 1, level)` → `hint-cu-<slug>-s1-l<level>`
    (기존 규칙 재사용).
  - `problem_id` = CU의 `problem_id` 그대로(측정기 `g3_content_measures`의 조인 키).
  - `revealed_concept_ids` = `("unmatched-concept:<개념 이름>",)` — CU에는 개념 태깅이 없고
    (`concepts: []`) LLM이 낸 개념 이름은 원자 백본 코드(`atom_node.code`)에 **매칭되지
    않았다**. 원자 코드를 지어내지 않고 미매칭임을 이름공간으로 드러낸다(개념 ID 매칭 = LLM
    핵심 호출지점 ④ — 후속).

게이트 맥락: `GateContext(step_contents=LLM이 낸 단계, concept_name=LLM이 낸 개념 이름,
final_answer=CU answer, value_exposure=주입된 능력)`. 값 축 능력은 `populate.main`이 받는 것과 같은
기본 구현(수학 `math_answer_value_exposure`)을 프로세스 시작점이 내려 준다. **None을 넘기면 값 축을
판정하지 못하므로 모든 힌트가 거부된다**(fail-closed — `GateContext` docstring).

⚠ 순환 측정 경고 (EOS-207 측정기와의 관계)
------------------------------------------
측정기 `ops/g3_content_measures`의 힌트 **기계 축**은 이 패스가 거른 바로 그 게이트 B
(`check_answer_leakage` — 글자 축 + 값 축)를 다시 돌린다. 그래서 verified 힌트만 담긴
`cu.hints.jsonl`에 대해 기계 축 누설은 **구조적으로 0**이다(같은 검출기로 거르고 같은
검출기로 잰다).
측정기 쪽은 개념 이름을 지우지 않고 본문 전체를 보므로 미세한 차이는 있으나(여기서는 개념 이름에
숫자·등호를 금해 그 차이를 막는다), 그 0은 **누설이 없다는 증거가 아니다**. 실질 검증은 의미 축
(사람 표본 검수 — EOS-210·§5 F-Ⅴ)이다. 측정기 출력의 `HINT_SEMANTIC_AXIS=NOT_MEASURED`가 그 사실을
늘 싣는다. 반대로 측정기에서 UNDECIDED가 나오는 경우는 실재한다 — 글자 축이 짧은 정답(1자)을
유보하면 게이트는 값 축만으로 통과시키지만 측정기는 사람 폴백(None)으로 센다.

범위 밖(정직한 공백): LLM이 낸 **단계 계산 자체의 기계 검산**(수식 엔진 검증 — 과목 어댑터
몫)은 하지 않는다(후속). 게이트 3종은 "힌트가 레벨에 맞게 드러내는가·정답을 흘리는가·톤이
안전한가"를 볼 뿐, 단계가 수학적으로 옳은지는 보지 않는다.

산출물(회차 폴더 = `data/runs/<좌석>/`, 줄마다 즉시 flush — 도중에 끊겨도 증거가 남는다)
--------------------------------------------------------------------------------------
  - `cu.hints.jsonl`          verified=true `Hint` JSON 1행 1건 — 학생에게 나갈 집합이자 측정 입력.
  - `cu.hints.rejected.jsonl` 게이트 거부 `Hint` JSON(gate_report에 게이트별 사유).
  - `cu.hints.genlog.jsonl`   LLM 호출마다 `GenerationLog` 1행(기존 `cu.genlog.jsonl`과 같은 모델) —
    model_name·prompt_version·seed·input_sha256 + success·error_detail(예외 타입명 포함).
  - `cu.hints.context.jsonl`  CU당 1행 — 게이트가 본 맥락(단계·개념 이름·정답)과 레벨별 판정.
    **이 행이 그 CU의 완료 표지**다(아래 재개). 게이트 판정을 재현하려면 이 맥락이 필요하다.

재개(resume) — 같은 CU 중복 생성 0
---------------------------------
CU 완료 = `cu.hints.context.jsonl`에 행이 있다. 쓰기 순서가 `힌트 → 거부 → 문맥`이라, 문맥 행 없이
힌트 행만 있는 CU는 지난 실행이 그 사이에 끊긴 것이다(고아 행). 재개 시 고아 행을 두 힌트 파일에서
걷어내고(원자적 교체 · 걷어낸 행 수를 요약에 싣는다) 그 CU를 다시 만든다. 생성 로그는 append
전용이라 걷어내지 않는다(호출이 실제로 있었다는 기록이다).

종료 코드 (요약은 `KEY=VALUE` 줄, 마지막 줄 `EXIT=<n>`)
----------------------------------------------------
  - 0 — `cu.jsonl`의 CU **전부**가 L1·L2·L3 모두 verified다.
  - 1 — 일부 CU가 미완이다: 재시도 후에도 생성 실패(`FAILED_CUS`) · 게이트가 한 레벨 이상 거부
    (`INCOMPLETE_CUS`) · `--limit`로 이번 실행에서 처리하지 않음(`CU_PENDING`) · 생성 로그
    기록 실패.
  - 2 — 입력 오류: 회차 폴더·`cu.jsonl` 부재·파싱 실패·필수 필드 결측·CU 0건·자체 저작이 아닌 CU
    (클라우드 반출 등급 선언이 거짓이 된다)·기존 산출물 손상. 이 경우 **LLM을 한 번도
    부르지 않는다**.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from whymath_backend.config import Settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.escalation_defaults import default_student_escalation_signals
from whymath_backend.l3.generation_seed import SeedSource, seed_for_decision
from whymath_backend.l3.interfaces import LLMProvider, TraceSink
from whymath_backend.l3.models import CostTier, GenerationResult, RoutingDecision, RoutingRequest
from whymath_backend.l3.pregenerate.provenance_bridge import (
    actual_cost_usd_or_none,
    append_generation_log_jsonl,
    model_name_for_decision,
)
from whymath_backend.l3.providers.factory import cloud_provider_name
from whymath_backend.l3.router import Router, actual_cost_krw, langfuse_fields
from whymath_backend.l4.hint_content.cu_hint_prompts import (
    CU_HINT_OUTPUT_SCHEMA,
    CU_HINT_SYSTEM,
    build_cu_hint_user,
    cu_hint_prompt_version,
)
from whymath_backend.l4.hint_content.gates import GATE_NAMES, GateContext, evaluate_gates
from whymath_backend.l4.hint_content.generator import LEVEL_SOCRATIC_CATEGORY
from whymath_backend.l4.hint_content.models import (
    HINT_LEVELS,
    Hint,
    HintLevel,
    HintReveals,
    SolutionStepRef,
    hint_id_for,
)
from whymath_backend.schema.provenance import GenerationLog, text_sha256
from whymath_backend.schema.verification_capabilities import AnswerValueExposure

__all__ = [
    "CONTEXT_FILE",
    "CU_FILE",
    "CU_HINT_GENERATOR_VERSION",
    "CU_HINT_STEP_ORDER",
    "CU_PATH_PREFIX",
    "EXIT_INCOMPLETE",
    "EXIT_INPUT_ERROR",
    "EXIT_OK",
    "GENLOG_FILE",
    "HINTS_FILE",
    "REJECTED_FILE",
    "UNMATCHED_CONCEPT_PREFIX",
    "CuHintDraft",
    "CuInput",
    "DraftError",
    "PassReport",
    "build_arg_parser",
    "build_cu_hints",
    "cu_solution_path_id",
    "load_cu_inputs",
    "parse_draft",
    "routing_request_for",
    "run_cli",
    "run_cu_hint_pass",
]

_LOGGER = logging.getLogger("whymath.l4.hint_content.cu_hint_pass")

CU_FILE: Final[str] = "cu.jsonl"
HINTS_FILE: Final[str] = "cu.hints.jsonl"
REJECTED_FILE: Final[str] = "cu.hints.rejected.jsonl"
GENLOG_FILE: Final[str] = "cu.hints.genlog.jsonl"
CONTEXT_FILE: Final[str] = "cu.hints.context.jsonl"

EXIT_OK: Final[int] = 0
EXIT_INCOMPLETE: Final[int] = 1
EXIT_INPUT_ERROR: Final[int] = 2

CU_PATH_PREFIX: Final[str] = "cu-"
"""합성 풀이 경로 ID 접두 — 실제 경로(`sp-`)·평가 하네스(`aq-eval-`)와 겹치지 않는다."""

CU_HINT_STEP_ORDER: Final[int] = 1
"""세 힌트가 겨냥하는 단계 — 풀이를 시작하는 자리(모듈 docstring 합성 ID 규칙)."""

UNMATCHED_CONCEPT_PREFIX: Final[str] = "unmatched-concept:"
"""원자 코드에 매칭되지 않은 LLM 개념 이름의 이름공간 — 원자 코드를 지어내지 않는다."""

CU_HINT_GENERATOR_VERSION: Final[str] = "eos211-cu-llm-v1"
"""힌트 본문 생성 경로 판 — `Hint.generator_version`에는 `<판>@<prompt_version>`으로 싣는다."""

_KIND: Final[str] = "l4.hint_content.cu_hint_pass"
_DEFAULT_TEMPERATURE: Final[float] = 0.2
_DEFAULT_RETRIES: Final[int] = 2
# 라우팅 난이도 신호 — 문항 난이도가 아니라 힌트 저작 과업의 난이도(모듈 docstring).
_ROUTING_DIFFICULTY: Final[str] = "medium"
_SELF_AUTHORED_LICENSE: Final[str] = "WHYMATH_GENERATED"
_SELF_AUTHORED_SOURCE: Final[str] = "자체생성"
_LEVEL_KEYS: Final[dict[HintLevel, str]] = {1: "L1", 2: "L2", 3: "L3"}
# 개념 이름 금지 문자 — 게이트는 값 축을 돌리기 전에 개념 이름을 본문에서 지운다
# (`gates._value_text`).
# 개념 이름에 값·식이 들어가면 그 자리가 값 축의 사각이 되므로 수·등호·연산 기호를 금한다.
_CONCEPT_FORBIDDEN = re.compile(r"[0-9=+*/^<>]")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _norm(text: str) -> str:
    """비교용 정규화 — NFKC + 공백 제거(게이트 A의 정규화와 같은 규약 · 개념 이름 노출 파생용)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def cu_solution_path_id(slug: str) -> str:
    """CU slug → 결정론 합성 풀이 경로 ID(`cu-<slug>`)."""
    return f"{CU_PATH_PREFIX}{slug}"


# ──────────────────────────────────────────────────────────────────────────
# 입력 — 회차 폴더의 cu.jsonl
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CuInput:
    """힌트 패스가 읽는 CU 필드 — 지문·정답·해설·과목·성취기준·식별자."""

    problem_id: uuid.UUID
    slug: str
    question: str
    answer: str
    explanation: str | None
    subject: str
    standards: tuple[str, ...]


def _read_jsonl(path: Path) -> tuple[list[tuple[int, str, dict[str, Any]]], list[str]]:
    """JSONL → ([(줄 번호, 원문 줄, 객체)], 오류). 오류는 줄 번호·예외 타입명만(값 미포함)."""
    rows: list[tuple[int, str, dict[str, Any]]] = []
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return rows, [f"{path.name} 읽기 실패 — {type(exc).__name__}"]
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_no} JSON 파싱 실패 — {type(exc).__name__}")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{path.name}:{line_no} 객체가 아님({type(parsed).__name__})")
            continue
        rows.append((line_no, line, parsed))
    return rows, errors


def _req_str(row: Mapping[str, Any], key: str) -> str | None:
    value = row.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def load_cu_inputs(run_dir: Path) -> tuple[list[CuInput], list[str]]:
    """회차 폴더 → (CU 목록, 입력 오류). 오류가 하나라도 있으면 호출부는 LLM을 부르지 않는다.

    자체 저작 확인(`license`·`source_type`)은 라우팅 등급 선언(`SELF_AUTHORED_CORPUS`)의 전제다 —
    이 CU 본문을 클라우드 좌석에 실어 보내므로, 선언이 거짓이 되는 입력은 받지 않는다.
    """
    if not run_dir.is_dir():
        return [], [f"회차 폴더 {run_dir} 이(가) 디렉터리가 아니다"]
    cu_path = run_dir / CU_FILE
    if not cu_path.is_file():
        return [], [f"{run_dir.name}/{CU_FILE} 없음"]
    rows, errors = _read_jsonl(cu_path)
    cus: list[CuInput] = []
    seen_ids: set[uuid.UUID] = set()
    seen_slugs: set[str] = set()
    for line_no, _raw, row in rows:
        where = f"{CU_FILE}:{line_no}"
        missing = [
            k for k in ("problem_id", "slug", "question_text", "answer") if not _req_str(row, k)
        ]
        if missing:
            errors.append(f"{where} 필수 필드 결측 {missing}")
            continue
        try:
            problem_id = uuid.UUID(str(row["problem_id"]))
        except ValueError as exc:
            errors.append(f"{where} problem_id가 UUID가 아님 — {type(exc).__name__}")
            continue
        if row.get("license") != _SELF_AUTHORED_LICENSE or row.get("source_type") != (
            _SELF_AUTHORED_SOURCE
        ):
            errors.append(
                f"{where} 자체 저작 CU가 아님(license·source_type) — 반출 등급 선언"
                "(SELF_AUTHORED_CORPUS)이 거짓이 되므로 받지 않는다"
            )
            continue
        slug = str(_req_str(row, "slug"))
        if problem_id in seen_ids or slug in seen_slugs:
            errors.append(f"{where} problem_id·slug 중복")
            continue
        seen_ids.add(problem_id)
        seen_slugs.add(slug)
        raw_codes = row.get("achievement_standard_codes")
        standards = (
            tuple(c for c in raw_codes if isinstance(c, str)) if isinstance(raw_codes, list) else ()
        )
        cus.append(
            CuInput(
                problem_id=problem_id,
                slug=slug,
                question=str(_req_str(row, "question_text")),
                answer=str(_req_str(row, "answer")),
                explanation=_req_str(row, "answer_explanation"),
                subject=_req_str(row, "subject") or "",
                standards=standards,
            )
        )
    if not errors and not cus:
        errors.append(f"{run_dir.name}/{CU_FILE}에 CU가 0건 — 0건 처리를 성공으로 보고하지 않는다")
    return cus, errors


# ──────────────────────────────────────────────────────────────────────────
# LLM 출력 계약
# ──────────────────────────────────────────────────────────────────────────
class _HintTexts(BaseModel):
    """레벨별 힌트 본문 — 키는 정확히 L1·L2·L3."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    L1: str = Field(min_length=1, max_length=600)
    L2: str = Field(min_length=1, max_length=600)
    L3: str = Field(min_length=1, max_length=600)


class CuHintDraft(BaseModel):
    """CU 1건에 대한 LLM 출력 계약 — 단계 목록(2~8) · 핵심 개념 이름 · L1·L2·L3 본문.

    `extra="forbid"`: 계약 밖 키(예: 모델이 덧붙인 `answer`)는 스키마 위반이다 — 무엇을 버렸는지
    모르는 채로 일부만 쓰지 않는다. 위반은 그 호출의 실패로 기록되고 재시도된다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    steps: tuple[str, ...] = Field(min_length=2, max_length=8)
    concept_name: str = Field(min_length=2, max_length=30)
    hints: _HintTexts

    @field_validator("steps")
    @classmethod
    def _steps_non_empty(cls, steps: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(s.strip() for s in steps)
        if any(not s for s in cleaned):
            raise ValueError("빈 단계가 있다")
        if any(len(s) > 300 for s in cleaned):
            raise ValueError("단계 하나가 300자를 넘는다")
        return cleaned

    @field_validator("concept_name")
    @classmethod
    def _concept_has_no_value(cls, name: str) -> str:
        if _CONCEPT_FORBIDDEN.search(name):
            raise ValueError("개념 이름에 수·등호·연산 기호가 있다(값 축 사각 방지)")
        return name


class DraftError(Exception):
    """LLM 응답을 계약으로 받지 못함 — `detail`은 생성 로그 error_detail에 그대로 실린다."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _extract_json_text(raw: str) -> str:
    """관대 추출 — 코드 펜스·앞뒤 산문을 걷고 첫 `{`부터 마지막 `}`까지를 돌려준다."""
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


def parse_draft(raw: str) -> CuHintDraft:
    """원시 응답 → 계약. 실패는 `DraftError`(예외 타입명 + 위반 위치만 — 응답 값은 싣지 않는다)."""
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise DraftError(f"응답 JSON 파싱 실패: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise DraftError(f"응답 JSON 파싱 실패: 객체가 아님({type(data).__name__})")
    try:
        return CuHintDraft.model_validate(data)
    except ValidationError as exc:
        locs = sorted({".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()})
        raise DraftError(f"응답 스키마 위반: {type(exc).__name__} ({', '.join(locs)})") from exc


# ──────────────────────────────────────────────────────────────────────────
# Hint 조립 + 게이트
# ──────────────────────────────────────────────────────────────────────────
def build_cu_hints(cu: CuInput, draft: CuHintDraft, *, generator_version: str) -> tuple[Hint, ...]:
    """계약 → 검증 전 Hint 3건(L1·L2·L3). 노출 선언은 레벨 행렬을 따른다.

    - L1: 개념 이름 노출만(흐름·계산 X) — 본문에 개념 이름이 없으면 게이트 A가 거부한다.
    - L2: 흐름 노출(계산 X) · L3: 흐름 + 부분 시연. 두 레벨의 개념 이름 노출은 **본문에서 파생**한다
      (레벨 행렬이 둘 다 허용하므로 — `harness/ai_quality_judges._gate_hint` 선례).
    흐름·계산 노출은 레벨 선언 그대로 두고, 본문이 그 선언과 맞는지는 게이트 A가 판정한다.
    """
    path_id = cu_solution_path_id(cu.slug)
    concept_id = f"{UNMATCHED_CONCEPT_PREFIX}{draft.concept_name}"
    norm_concept = _norm(draft.concept_name)
    hints: list[Hint] = []
    for level in HINT_LEVELS:
        content = getattr(draft.hints, _LEVEL_KEYS[level])
        named = level == 1 or norm_concept in _norm(content)
        hints.append(
            Hint(
                hint_id=hint_id_for(path_id, CU_HINT_STEP_ORDER, level),
                solution_step_ref=SolutionStepRef(
                    solution_path_id=path_id,
                    step_order=CU_HINT_STEP_ORDER,
                    problem_id=cu.problem_id,
                ),
                level=level,
                reveals=HintReveals.from_flags(
                    concept_names=named,
                    step_flow=level >= 2,
                    partial_computation=level == 3,
                    revealed_concept_ids=(concept_id,) if named else (),
                ),
                content=content,
                socratic_category=LEVEL_SOCRATIC_CATEGORY[level],
                verified=False,
                gate_report={},
                generator_version=generator_version,
            )
        )
    return tuple(hints)


# ──────────────────────────────────────────────────────────────────────────
# 산출물 쓰기 — 줄마다 open→write→flush→close(도중에 끊겨도 앞의 줄은 남는다)
# ──────────────────────────────────────────────────────────────────────────
def _append_lines(path: Path, lines: Sequence[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
            handle.flush()


def _hint_line(hint: Hint) -> str:
    return hint.model_dump_json()


# ──────────────────────────────────────────────────────────────────────────
# 재개 상태 — 완료 CU·고아 행
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _ResumeState:
    done: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    discarded_orphan_rows: int = 0
    errors: list[str] = field(default_factory=list)


def _levels(value: object) -> frozenset[int] | None:
    if isinstance(value, list) and all(isinstance(v, int) and v in HINT_LEVELS for v in value):
        return frozenset(value)
    return None


def _load_hint_rows(
    path: Path, *, verified: bool, known: set[uuid.UUID], errors: list[str]
) -> list[tuple[str, Hint]]:
    """힌트 산출물 → [(원문 줄, Hint)]. 계약 위반·검증 상태 불일치·알 수 없는 CU는 오류."""
    if not path.is_file():
        return []
    rows, errs = _read_jsonl(path)
    errors.extend(errs)
    out: list[tuple[str, Hint]] = []
    for line_no, raw, row in rows:
        try:
            hint = Hint.model_validate(row)
        except ValidationError as exc:
            errors.append(f"{path.name}:{line_no} Hint 계약 위반 — {type(exc).__name__}")
            continue
        if hint.verified is not verified:
            errors.append(f"{path.name}:{line_no} verified={hint.verified} 행이 섞였다(손상)")
            continue
        if hint.solution_step_ref.problem_id not in known:
            errors.append(f"{path.name}:{line_no} cu.jsonl에 없는 CU의 힌트(다른 회차 행?)")
            continue
        out.append((raw, hint))
    return out


def _compact(path: Path, keep: Sequence[str]) -> None:
    """원자적 교체 — 같은 폴더 임시 파일에 남길 줄을 쓰고 `os.replace`(중간 상태 노출 0)."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for line in keep:
            handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _load_resume_state(run_dir: Path, cus: Sequence[CuInput]) -> _ResumeState:
    """기존 산출물 → 완료 CU·고아 정리. 손상은 오류로 돌려 LLM 호출 전에 멈춘다."""
    state = _ResumeState()
    known = {cu.problem_id for cu in cus}
    context_path = run_dir / CONTEXT_FILE
    if context_path.is_file():
        rows, errs = _read_jsonl(context_path)
        state.errors.extend(errs)
        for line_no, _raw, row in rows:
            try:
                pid = uuid.UUID(str(row.get("problem_id")))
            except ValueError as exc:
                state.errors.append(
                    f"{CONTEXT_FILE}:{line_no} problem_id 손상 — {type(exc).__name__}"
                )
                continue
            verified, rejected = _levels(row.get("verified_levels")), _levels(
                row.get("rejected_levels")
            )
            if pid not in known or pid in state.done or verified is None or rejected is None:
                state.errors.append(f"{CONTEXT_FILE}:{line_no} 알 수 없는 CU·중복·레벨 손상")
                continue
            if verified | rejected != frozenset(HINT_LEVELS) or verified & rejected:
                state.errors.append(
                    f"{CONTEXT_FILE}:{line_no} 레벨 판정이 L1·L2·L3를 나누지 않는다"
                )
                continue
            state.done[pid] = row
    accepted = _load_hint_rows(
        run_dir / HINTS_FILE, verified=True, known=known, errors=state.errors
    )
    rejected_rows = _load_hint_rows(
        run_dir / REJECTED_FILE, verified=False, known=known, errors=state.errors
    )
    if state.errors:
        return state
    # 완료 CU는 행이 문맥 판정과 정확히 맞아야 한다 — 어긋나면 손상(사람이 봐야 한다).
    for pid, ctx in state.done.items():
        got_acc = sorted(h.level for _, h in accepted if h.solution_step_ref.problem_id == pid)
        got_rej = sorted(h.level for _, h in rejected_rows if h.solution_step_ref.problem_id == pid)
        if got_acc != sorted(ctx["verified_levels"]) or got_rej != sorted(ctx["rejected_levels"]):
            state.errors.append(f"완료 CU {ctx.get('slug')}의 힌트 행이 문맥 판정과 다르다(손상)")
    if state.errors:
        return state
    # 고아 행(문맥 없이 힌트만 있는 CU) — 지난 실행이 그 CU 도중에 끊겼다. 걷어내고 다시 만든다.
    for path, hint_rows in (
        (run_dir / HINTS_FILE, accepted),
        (run_dir / REJECTED_FILE, rejected_rows),
    ):
        orphans = [raw for raw, h in hint_rows if h.solution_step_ref.problem_id not in state.done]
        if orphans:
            keep = [raw for raw, h in hint_rows if h.solution_step_ref.problem_id in state.done]
            _compact(path, keep)
            state.discarded_orphan_rows += len(orphans)
    return state


# ──────────────────────────────────────────────────────────────────────────
# 리포트
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PassReport:
    """패스 1회 정직 회계 — 수치는 전부 실측(조용한 생략 0)."""

    run_dir: str
    prompt_version: str
    input_errors: list[str] = field(default_factory=list)
    cu_total: int = 0
    cu_resumed: int = 0
    cu_processed: int = 0
    calls: int = 0
    calls_failed: int = 0
    failed_cus: list[str] = field(default_factory=list)
    incomplete_cus: list[str] = field(default_factory=list)
    pending_cus: list[str] = field(default_factory=list)
    complete_cus: int = 0
    measurable_cus: int = 0
    hints_generated: int = 0
    verified_by_level: Counter[int] = field(default_factory=Counter)
    rejected_by_gate: Counter[str] = field(default_factory=Counter)
    failure_kinds: Counter[str] = field(default_factory=Counter)
    routes: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    discarded_orphan_rows: int = 0
    genlog_errors: int = 0

    @property
    def exit_code(self) -> int:
        if self.input_errors:
            return EXIT_INPUT_ERROR
        if self.failed_cus or self.incomplete_cus or self.pending_cus or self.genlog_errors:
            return EXIT_INCOMPLETE
        return EXIT_OK

    def render_lines(self) -> list[str]:
        """요약 `KEY=VALUE` 줄 — 마지막 줄은 항상 `EXIT=<n>`."""

        def j(value: object) -> str:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)

        by_level = {f"L{k}": v for k, v in sorted(self.verified_by_level.items())}

        lines = [
            f"RUN_DIR={self.run_dir}",
            f"PROMPT_VERSION={self.prompt_version}",
            f"INPUT_ERRORS={len(self.input_errors)}",
            f"CU_TOTAL={self.cu_total}",
            f"CU_RESUMED={self.cu_resumed}",
            f"CU_PROCESSED={self.cu_processed}",
            f"CU_PENDING={len(self.pending_cus)}",
            f"CU_COMPLETE={self.complete_cus}",
            f"CU_MEASURABLE_L12={self.measurable_cus}",
            f"CU_INCOMPLETE={len(self.incomplete_cus)}",
            f"CU_GENERATION_FAILED={len(self.failed_cus)}",
            f"CALLS={self.calls}",
            f"CALLS_FAILED={self.calls_failed}",
            f"CALL_FAILURE_KINDS={j(dict(self.failure_kinds))}",
            f"ROUTES={j(dict(self.routes))}",
            f"MODELS={j(dict(self.models))}",
            f"HINTS_GENERATED={self.hints_generated}",
            f"HINTS_VERIFIED={sum(self.verified_by_level.values())}",
            f"VERIFIED_BY_LEVEL={j(by_level)}",
            f"REJECTED_BY_GATE={j({g: self.rejected_by_gate[g] for g in GATE_NAMES})}",
            f"RESUME_DISCARDED_ORPHAN_ROWS={self.discarded_orphan_rows}",
            f"GENLOG_WRITE_ERRORS={self.genlog_errors}",
        ]
        lines.extend(f"INPUT_ERROR={e}" for e in self.input_errors)
        lines.append(f"FAILED_CUS={','.join(self.failed_cus)}")
        lines.append(f"INCOMPLETE_CUS={','.join(self.incomplete_cus)}")
        lines.append(f"PENDING_CUS={','.join(self.pending_cus)}")
        lines.append(f"EXIT={self.exit_code}")
        return lines


# ──────────────────────────────────────────────────────────────────────────
# LLM 호출 1회 (라우터 경유) + 생성 로그
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _CallContext:
    provider: LLMProvider
    trace: TraceSink | None
    settings: Settings | None
    seed_source: SeedSource | None
    subscription: str | None
    budget_krw: float | None
    temperature: float
    on_progress: Callable[[str], None] | None
    genlog_path: Path
    run_id: str
    prompt_version: str


def routing_request_for(*, subscription: str | None, budget_krw: float | None) -> RoutingRequest:
    """라우팅 신호 — 오프라인 배치(비동기 허용)·저작 과업·자체 저작 등급(모듈 docstring).

    공개 함수인 이유: 런북의 좌석 자가검증이 **패스가 실제로 쓰는 바로 이 함수**로 라우터에
    묻게 하기 위해서다(따로 손으로 만든 요청을 검사하면 패스와 다른 경로를 검사하게 된다).
    None은 "지정 안 함" — 학생 기본 신호(`default_student_escalation_signals`, 오늘은 free·0)를
    쓴다.
    """
    defaults = default_student_escalation_signals()
    return RoutingRequest(
        task_type="generate",
        difficulty=_ROUTING_DIFFICULTY,
        requires_reasoning=True,
        student_subscription=(
            subscription if subscription is not None else defaults.student_subscription
        ),
        budget_krw=budget_krw if budget_krw is not None else defaults.budget_krw,
        sync=False,
        # 프롬프트에 실리는 것은 자체 저작 CU(WHYMATH_GENERATED — `load_cu_inputs`가 확인)뿐이다.
        data_licenses=SELF_AUTHORED_CORPUS,
    )


def _progress(call: _CallContext, line: str) -> None:
    """진행 줄 — 장시간 배치가 멈췄는지 사람이 볼 수 있게 CU마다 1줄(요약 줄과 접두가 다르다)."""
    if call.on_progress is not None:
        call.on_progress(line)


def _is_local(decision: RoutingDecision) -> bool:
    return decision.cost_tier == CostTier.LOCAL.value


def _route_label(decision: RoutingDecision) -> str:
    return f"{decision.cost_tier}:{decision.local_family or '-'}:{decision.local_model or '-'}"


def _record_trace(call: _CallContext, decision: RoutingDecision, result: GenerationResult) -> None:
    """Langfuse 관측(모든 LLM 호출 추적) — never-break, 실패는 예외 타입명을 남긴다."""
    if call.trace is None:
        return
    usage = result.usage
    cost: float | None = None
    try:
        seat = None if _is_local(decision) else cloud_provider_name(call.settings)
        if usage is not None and (
            _is_local(decision)
            or (usage.input_tokens is not None and usage.output_tokens is not None)
        ):
            cost = actual_cost_krw(decision, usage, seat=seat)
        call.trace.record(
            langfuse_fields(decision, cache_hit=False, usage=usage, cost_krw=cost, cloud_seat=seat)
        )
    except Exception as exc:  # noqa: BLE001 — 관측 장애가 배치를 깨면 안 된다(타입명 로그)
        _LOGGER.warning("CU 힌트 패스 관측 기록 실패(%s) — 무시하고 계속", type(exc).__name__)


def _emit_genlog(
    call: _CallContext,
    report: PassReport,
    *,
    cu: CuInput,
    prompt: str,
    decision: RoutingDecision,
    result: GenerationResult | None,
    seed: int | None,
    error_detail: str | None,
) -> str | None:
    """호출 1건 → `GenerationLog` 1행 즉시 append. 실패는 타입명 로그 + 회계(종료 코드 1)."""
    usage = result.usage if result is not None else None
    try:
        model_name = model_name_for_decision(decision, settings=call.settings)
        seat = None if _is_local(decision) else cloud_provider_name(call.settings)
        latency = int(round(usage.latency_ms)) if usage and usage.latency_ms is not None else None
        log = GenerationLog(
            model_name=model_name,
            prompt_version=call.prompt_version,
            seed=seed,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_input_tokens=usage.cache_read_input_tokens if usage else None,
            cache_creation_input_tokens=usage.cache_creation_input_tokens if usage else None,
            served_model=usage.served_model if usage else None,
            retries=usage.retries if usage else None,
            cost_usd=actual_cost_usd_or_none(decision, usage, seat=seat),
            latency_ms=latency,
            success=error_detail is None,
            error_detail=error_detail,
            input_snapshot={
                "kind": _KIND,
                "prompt": prompt,
                "system": CU_HINT_SYSTEM,
                "prompt_sha256": text_sha256(prompt),
                "system_sha256": text_sha256(CU_HINT_SYSTEM),
                "cu": {"slug": cu.slug, "problem_id": str(cu.problem_id)},
                "temperature": call.temperature,
            },
            # 이 호출이 겨냥한 CU — 성공·실패 모두 같은 정체성(입력 CU가 처음부터 정해져 있다).
            cu_slug=cu.slug,
        )
        stamped = append_generation_log_jsonl(call.genlog_path, log, run_id=call.run_id)
        report.models[model_name] += 1
        return str(stamped.log_id)
    except Exception as exc:  # noqa: BLE001 — 기록 실패를 삼키지 않는다(회계 + 타입명)
        report.genlog_errors += 1
        _LOGGER.warning(
            "CU 힌트 생성 로그 기록 실패(%s) — 종료 코드 1로 드러낸다", type(exc).__name__
        )
        return None


async def _attempt(
    call: _CallContext, report: PassReport, cu: CuInput, prompt: str
) -> tuple[CuHintDraft | None, RoutingDecision, str | None]:
    """라우터 결정 → 호출 → 로그 → 파싱. (계약 또는 None, 결정, 성공 호출의 log_id)."""
    decision = Router().route(
        routing_request_for(subscription=call.subscription, budget_krw=call.budget_krw)
    )
    report.routes[_route_label(decision)] += 1
    seed = seed_for_decision(decision, source=call.seed_source)
    kwargs: dict[str, Any] = {"temperature": call.temperature}
    if _is_local(decision):
        kwargs["json_schema"] = (
            CU_HINT_OUTPUT_SCHEMA  # Ollama 제약 디코딩(클라우드는 거부하므로 뺀다)
        )
    if seed is not None:
        kwargs["seed"] = seed
    report.calls += 1
    try:
        result = await call.provider.generate(prompt, CU_HINT_SYSTEM, decision, **kwargs)
    except Exception as exc:  # noqa: BLE001 — provider 장애는 재시도 대상(타입명 기록)
        report.calls_failed += 1
        report.failure_kinds["provider"] += 1
        detail = f"provider.generate failed: {type(exc).__name__}: {exc}"
        _LOGGER.warning("CU 힌트 provider 호출 실패(%s) — %s", type(exc).__name__, cu.slug)
        _emit_genlog(
            call,
            report,
            cu=cu,
            prompt=prompt,
            decision=decision,
            result=None,
            seed=seed,
            error_detail=detail,
        )
        return None, decision, None
    _record_trace(call, decision, result)
    try:
        draft = parse_draft(result.text)
    except DraftError as exc:
        report.calls_failed += 1
        report.failure_kinds["parse" if "파싱" in exc.detail else "schema"] += 1
        _LOGGER.warning("CU 힌트 응답 거부(%s) — %s", exc.detail, cu.slug)
        _emit_genlog(
            call,
            report,
            cu=cu,
            prompt=prompt,
            decision=decision,
            result=result,
            seed=seed,
            error_detail=exc.detail,
        )
        return None, decision, None
    log_id = _emit_genlog(
        call,
        report,
        cu=cu,
        prompt=prompt,
        decision=decision,
        result=result,
        seed=seed,
        error_detail=None,
    )
    return draft, decision, log_id


# ──────────────────────────────────────────────────────────────────────────
# 패스 본체
# ──────────────────────────────────────────────────────────────────────────
async def run_cu_hint_pass(
    run_dir: Path,
    *,
    provider: LLMProvider,
    value_exposure: AnswerValueExposure | None,
    trace: TraceSink | None = None,
    settings: Settings | None = None,
    retries: int = _DEFAULT_RETRIES,
    limit: int | None = None,
    subscription: str | None = None,
    budget_krw: float | None = None,
    temperature: float = _DEFAULT_TEMPERATURE,
    seed_source: SeedSource | None = None,
    run_id: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> PassReport:
    """회차 폴더 1개에 사후 힌트 패스를 돈다.

    `value_exposure`는 필수 키워드다(None = 값 축 fail-closed). 입력 오류가 있으면 LLM을 한 번도
    부르지 않고 리포트만 돌려준다(종료 코드 2).
    """
    prompt_version = cu_hint_prompt_version()
    report = PassReport(run_dir=str(run_dir), prompt_version=prompt_version)
    if retries < 0:
        report.input_errors.append(f"retries는 0 이상이어야 한다(받은 값 {retries})")
        return report
    if limit is not None and limit < 1:
        report.input_errors.append(f"limit는 1 이상이어야 한다(받은 값 {limit})")
        return report
    cus, errors = load_cu_inputs(run_dir)
    report.cu_total = len(cus)
    if errors:
        report.input_errors.extend(errors)
        return report
    state = _load_resume_state(run_dir, cus)
    if state.errors:
        report.input_errors.extend(state.errors)
        return report
    report.discarded_orphan_rows = state.discarded_orphan_rows

    call = _CallContext(
        provider=provider,
        trace=trace,
        settings=settings,
        seed_source=seed_source,
        subscription=subscription,
        budget_krw=budget_krw,
        on_progress=on_progress,
        temperature=temperature,
        genlog_path=run_dir / GENLOG_FILE,
        run_id=run_id or uuid.uuid4().hex,
        prompt_version=prompt_version,
    )
    generator_version = f"{CU_HINT_GENERATOR_VERSION}@{prompt_version}"

    for cu in cus:
        if cu.problem_id in state.done:
            report.cu_resumed += 1
            _tally_levels(report, cu, state.done[cu.problem_id])
            continue
        if limit is not None and report.cu_processed >= limit:
            report.pending_cus.append(cu.slug)
            continue
        report.cu_processed += 1
        prompt = build_cu_hint_user(
            question=cu.question,
            answer=cu.answer,
            explanation=cu.explanation,
            subject=cu.subject,
            standards=cu.standards,
        )
        draft: CuHintDraft | None = None
        decision: RoutingDecision | None = None
        log_id: str | None = None
        for _ in range(retries + 1):
            draft, decision, log_id = await _attempt(call, report, cu, prompt)
            if draft is not None:
                break
        if draft is None or decision is None:
            report.failed_cus.append(cu.slug)
            _progress(call, f"CU_FAILED slug={cu.slug} attempts={retries + 1}")
            continue
        context_row = _gate_and_write(
            run_dir,
            report,
            cu,
            draft,
            value_exposure=value_exposure,
            generator_version=generator_version,
            extra={
                "prompt_version": prompt_version,
                "route": _route_label(decision),
                "genlog_log_id": log_id,
                "run_id": call.run_id,
            },
        )
        _tally_levels(report, cu, context_row)
        _progress(
            call,
            f"CU_DONE slug={cu.slug} verified_levels={context_row['verified_levels']} "
            f"rejected_levels={context_row['rejected_levels']} "
            f"processed={report.cu_processed}/{len(cus) - report.cu_resumed}",
        )

    flush = getattr(trace, "flush", None)
    if callable(flush):
        try:
            flush()
        except Exception as exc:  # noqa: BLE001 — 전송 확정 실패가 결과를 깨면 안 된다(타입명 로그)
            _LOGGER.warning("CU 힌트 패스 관측 flush 실패(%s)", type(exc).__name__)
    return report


def _gate_and_write(
    run_dir: Path,
    report: PassReport,
    cu: CuInput,
    draft: CuHintDraft,
    *,
    value_exposure: AnswerValueExposure | None,
    generator_version: str,
    extra: Mapping[str, object],
) -> dict[str, Any]:
    """게이트 3종 → 통과분·거부분 쓰기 → 문맥 행(완료 표지) 쓰기. 쓰기 순서가 재개 계약이다."""
    ctx = GateContext(
        step_contents=draft.steps,
        concept_name=draft.concept_name,
        final_answer=cu.answer,
        value_exposure=value_exposure,
    )
    gated = [
        evaluate_gates(h, ctx)
        for h in build_cu_hints(cu, draft, generator_version=generator_version)
    ]
    report.hints_generated += len(gated)
    accepted = [h for h in gated if h.verified]
    rejected = [h for h in gated if not h.verified]
    for hint in accepted:
        report.verified_by_level[hint.level] += 1
    for hint in rejected:
        for gate in GATE_NAMES:
            verdict = hint.gate_report.get(gate)
            if not (isinstance(verdict, dict) and verdict.get("passed") is True):
                report.rejected_by_gate[gate] += 1
    _append_lines(run_dir / HINTS_FILE, [_hint_line(h) for h in accepted])
    _append_lines(run_dir / REJECTED_FILE, [_hint_line(h) for h in rejected])
    context_row: dict[str, Any] = {
        "problem_id": str(cu.problem_id),
        "slug": cu.slug,
        "solution_path_id": cu_solution_path_id(cu.slug),
        "step_order": CU_HINT_STEP_ORDER,
        "steps": list(draft.steps),
        "concept_name": draft.concept_name,
        "final_answer": cu.answer,
        "generator_version": generator_version,
        "verified_levels": sorted(h.level for h in accepted),
        "rejected_levels": sorted(h.level for h in rejected),
        "written_at": datetime.now(UTC).isoformat(),
        **extra,
    }
    _append_lines(run_dir / CONTEXT_FILE, [json.dumps(context_row, ensure_ascii=False)])
    return context_row


def _tally_levels(report: PassReport, cu: CuInput, context_row: Mapping[str, Any]) -> None:
    """CU 상태 회계 — 완료(L1·L2·L3 verified)·측정 가능(L1·L2 verified)·미완."""
    verified = set(context_row.get("verified_levels") or [])
    if verified >= {1, 2}:
        report.measurable_cus += 1
    if verified >= set(HINT_LEVELS):
        report.complete_cus += 1
    else:
        report.incomplete_cus.append(cu.slug)


# ──────────────────────────────────────────────────────────────────────────
# CLI 본체 — 프로세스 시작점(`harness/cu_hint_pass.py`)이 provider·관측·값 축 능력을 내려 준다
# ──────────────────────────────────────────────────────────────────────────
def build_arg_parser(prog: str) -> argparse.ArgumentParser:
    """CLI 인자 — 저작 CLI(`problem_corpus_accumulate`)의 좌석 신호와 같은 이름을 쓴다."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "저장된 CU에 LLM으로 단계 목록과 L1·L2·L3 힌트를 붙이고 게이트 3종 통과분만 verified로 "
            "내보낸다(EOS-211). exit 0=전 CU 완료 · 1=일부 미완 · 2=입력 오류."
        ),
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="회차 좌석 폴더(cu.jsonl 보유)")
    parser.add_argument(
        "--retries", type=int, default=_DEFAULT_RETRIES, help="같은 CU 재시도 횟수(기본 2)"
    )
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 새로 처리할 CU 상한")
    parser.add_argument(
        "--subscription",
        default=None,
        choices=["free", "basic", "premium", "gifted"],
        help="라우팅 신호(구독). 클라우드 좌석은 --budget-krw와 함께여야 한다",
    )
    parser.add_argument("--budget-krw", type=float, default=None, help="라우팅 신호(예산·원)")
    parser.add_argument(
        "--temperature", type=float, default=_DEFAULT_TEMPERATURE, help="샘플링 온도(기본 0.2)"
    )
    return parser


def run_cli(
    argv: Sequence[str] | None,
    *,
    prog: str,
    provider_factory: Callable[[], LLMProvider],
    trace_factory: Callable[[], TraceSink | None],
    value_exposure: AnswerValueExposure | None,
) -> int:
    """인자 해석 → 패스 → 요약 출력 → 종료 코드. provider는 인자 검증 *뒤에* 만든다."""
    args = build_arg_parser(prog).parse_args(list(argv) if argv is not None else None)
    report = asyncio.run(
        run_cu_hint_pass(
            args.run_dir,
            provider=provider_factory(),
            value_exposure=value_exposure,
            trace=trace_factory(),
            retries=args.retries,
            limit=args.limit,
            subscription=args.subscription,
            budget_krw=args.budget_krw,
            on_progress=lambda line: print(line, flush=True),
            temperature=args.temperature,
        )
    )
    print("\n".join(report.render_lines()))
    return report.exit_code
