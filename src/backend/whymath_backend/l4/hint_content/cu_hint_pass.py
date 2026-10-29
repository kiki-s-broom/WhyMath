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
  - `cu.hints.jsonl`          **현재 채택본**의 verified=true `Hint` JSON 1행 1건 — 학생에게 나갈
    집합이자 측정 입력. CU별로 원자적 교체(`os.replace`)로만 쓴다.
  - `cu.hints.rejected.jsonl` 게이트 거부 `Hint` JSON(gate_report에 게이트별 사유) — **이력**이다.
    재생성해도 지우지 않는다(append 전용).
  - `cu.hints.genlog.jsonl`   LLM 호출(시도)마다 `GenerationLog` 1행 — **이력**(append 전용). 기존
    `cu.genlog.jsonl`과 같은 모델: model_name·prompt_version·seed·input_sha256 +
    success·error_detail.
    `log_id` = 시도 ID(채택본 `Hint.generator_version`의 `#<12hex>` 꼬리와 같은 값).
  - `cu.hints.context.jsonl`  CU당 1행(현재 채택본) — 게이트가 본 맥락(단계·개념 이름·정답)·레벨별
    판정·시도 회계(총 시도·게이트 도달 시도·거부 힌트 수). 원자적 교체로만 쓴다.

재생성·재시도 예산 (P2-1 — 게이트 거부도 다시 만든다)
--------------------------------------------------
`--retries N`이면 **CU 1건의 총 시도 상한 = N+1회**이고, 그 수는 그 CU의 **첫 시도부터**(이전 실행
포함 — 생성 로그의 그 CU 행 수) 센다. 시도 하나는 provider 실패·JSON 파싱 실패·계약 위반·**게이트
거부**(L1·L2·L3 중 하나라도 미통과) 중 무엇으로 끝나든 1회이며, 생성 로그에 1행을 남긴다. 세 레벨이
모두 통과하면 그 시도를 채택하고 멈춘다. 예산이 다 떨어지면 게이트까지 간 시도 중 **통과 레벨이 가장
많은 것**(같으면 나중 것 — 이전 실행의 채택본도 후보다)을 채택본으로 남긴다.

⚠ **선택 편향(정직한 공개)**: 게이트 거부 재생성은 "검출기를 통과할 때까지 다시 뽑기"다. 그래서
채택본은 게이트 B를 통과하도록 **골라진** 표본이고, 측정기의 기계 축(같은 게이트 B)이 0을 내는 것은
원래도 순환이었지만 재생성으로 그 순환이 더 강해진다. 이것을 상쇄하는 것은 의미 축(사람 표본 검수 —
EOS-210)이며, 숨기지 않기 위해 요약 줄이 **시도 수·게이트 거부율**을 늘
싣는다(`HINT_ATTEMPTS_TOTAL`·
`HINT_GATED_ATTEMPTS_TOTAL`·`HINT_GATE_REJECTED_HINTS_TOTAL`·`HINT_GATE_REJECT_RATE`·
`CU_REGENERATED`· `CU_ATTEMPTS`). 측정 해석에서 거부율이 높은 좌석일수록 채택본이 "운 좋게 통과한 한
장"일 가능성이 크다 — 의미 축 표본은 재생성된 CU(`CU_REGENERATED`)를 우선 포함해야 한다.

재개(resume) — 완료 = L1·L2·L3 모두 verified
------------------------------------------
재실행하면 **완료 CU는 호출 없이 건너뛴다.** 미완 CU(한 레벨 이상 미통과·채택본 없음)는 시도 예산이
남았으면 남은 만큼 다시 만들고, 예산이 떨어졌으면 건너뛴다(`CU_BUDGET_EXHAUSTED`) —
`--redo-incomplete`를 주면 그 실행에서 예산을 새로 N+1회 준다(총 시도 수는 그대로 누적 기록된다).
다시 만들 때 그 CU의 이전 채택본 힌트·문맥 행은 원자적으로 교체되고, 거부 기록·생성 로그(이력)는
그대로 남는다.

무결성: 채택본 두 파일은 **하나의 교체 단위**다 — 교체 전에 직전 내용을
보존본(`cu.hints.state.bak.json`)에 쓰고, 문맥 → 힌트 순서로 교체한 뒤 보존본을 지운다. 그 사이에서
끊기면 다음 실행이 보존본으로 직전 정합 상태를 복원한다(`RESUME_RESTORED_FROM_BACKUP`). 끊긴 원자적
쓰기의 `<파일>.tmp`는 재개 시작에서 지운다 (`RESUME_REMOVED_TMP`). 그래도 채택본 힌트 행이 문맥
행과 레벨 집합·`generator_version`(시도 ID 포함)이 맞지 않으면(외부 편집 등) 그 CU를 걷어내고
미완으로 다룬다(`RESUME_DISCARDED_INCONSISTENT_ROWS`). 요약의 `THIS_RUN_*`는 이번 실행분,
`TOTAL_*`는 채택본 파일 기준 누적이다(판정은 누적으로 한다). append 전용 파일(생성 로그·거부
기록)의 끊긴 마지막 줄·깨진 줄은 append 전에 `<파일>.corrupt`로 옮겨 보존하고 본 파일에서
걷어낸다(`GENLOG_QUARANTINED_LINES`· `REJECTED_QUARANTINED_LINES`) — 영구 손상 행이 남지 않는다.
원자적 교체로만 쓰는 두 파일(채택본·문맥)이 깨져 있으면 외부 손상이므로 입력 오류(2)로 멈춘다 (복구
= `--quarantine-damaged-state`로 다시 돌리기 — 런북 [R]).

생성 로그 `error_detail`에는 예외 **원문을 싣지 않는다**(`<단계 앞머리>: <타입명>(HTTP nnn)` — 이
파일은 산출물 브랜치로 원격에 올라간다). Langfuse 관측은 응답을 받은 호출만 기록한다 — provider 예외
호출은 선례(`l3/equivalent/llm_generator`·`l3/pipeline`)와 같이 관측하지 않고, 그 시도는 생성
로그(인프로세스 이중 회계)에 남는다.

종료 코드 (요약은 `KEY=VALUE` 줄, 마지막 줄 `EXIT=<n>`)
----------------------------------------------------
  - 0 — `cu.jsonl`의 CU **전부**가 L1·L2·L3 모두 verified다.
  - 1 — 일부 CU가 미완이다: 재시도 후에도 생성 실패(`FAILED_CUS`) · 게이트가 한 레벨 이상 거부
    (`INCOMPLETE_CUS`) · 시도 예산 소진(`CU_BUDGET_EXHAUSTED`) · `--limit`로 이번 실행에서 처리하지
    않음(`CU_PENDING`) · 생성 로그 기록 실패(**첫 실패에서 패스를 멈춘다** —
    `PASS_STOPPED=genlog_write_failed`. 기록 없는 호출은 예산 회계에서 빠져 같은 CU를 다시 부르게
    되므로 더 부르지 않는다).
  - 2 — 입력 오류: 회차 폴더·`cu.jsonl` 부재·파싱 실패·필수 필드 결측·CU 0건·자체 저작이 아닌 CU
    (클라우드 반출 등급 선언이 거짓이 된다)·기존 산출물 손상. 이 경우 **LLM을 한 번도
    부르지 않는다**.
  - 3 — 처리되지 않은 예외(디스크·권한 오류 등). 요약은 `UNHANDLED_ERROR=<타입명>`과 `EXIT=3` 두
  줄이다
    — 1(미완)과 섞이지 않게 따로 둔다.
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
    "EXIT_UNHANDLED",
    "GENLOG_FILE",
    "HINTS_FILE",
    "REJECTED_FILE",
    "STATE_BACKUP_FILE",
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
STATE_BACKUP_FILE: Final[str] = "cu.hints.state.bak.json"
"""채택본 교체 직전 상태의 보존본 — 교체 도중 끊기면 재개가 이것으로 직전 정합 상태를 복원한다."""

EXIT_OK: Final[int] = 0
EXIT_INCOMPLETE: Final[int] = 1
EXIT_INPUT_ERROR: Final[int] = 2
EXIT_UNHANDLED: Final[int] = 3

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
# (`gates._value_text`). 개념 이름에 값·식이 들어가면 그 자리가 값 축의 사각이 되므로 수·등호·
# 연산 기호·수 상수 기호를 금한다. **NFKC 정규화 뒤에** 검사한다 — 전각 `３`·분수 `½`(→ `1⁄2`)는
# 정규화 전에는 ASCII 범위를 피해 간다. `π`·`√`·`∞`는 NFKC로도 바뀌지 않으므로 직접 적는다.
_CONCEPT_FORBIDDEN = re.compile(r"[0-9=+*/^<>⁄√π∞]")
# 정답 포함 검사의 최소 길이(정규화 후) — 1자 정답(`4`·`e`·`a`)은 개념 이름의 흔한 글자와 우연히
# 겹친다(예: 정답 `e`와 「자연상수 e」·「집합의 원소」 속 영문자). 숫자 1자는 위 금지 문자가 이미
# 막고,
# 영문 1자는 오탐이 커 판정하지 않는다 — 게이트 B 글자 축(`detect_answer_leakage`)의 1자 유보,
# 게이트 A의 `_MIN_DECIDABLE_LEN`(2)과 같은 규약이다.
_MIN_ANSWER_CONTAIN_LEN: Final[int] = 2
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
        normalized = unicodedata.normalize("NFKC", name)
        if _CONCEPT_FORBIDDEN.search(normalized):
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


def parse_draft(raw: str, *, answer: str | None = None) -> CuHintDraft:
    """원시 응답 → 계약. 실패는 `DraftError`(예외 타입명 + 위반 위치만 — 응답 값은 싣지 않는다).

    `answer`를 주면 정규화한 정답이 정규화한 개념 이름에 들어 있는지도 본다(2자 이상일 때만 —
    `_MIN_ANSWER_CONTAIN_LEN` 근거). 들어 있으면 계약 위반이다(정답 값은 사유에 싣지 않는다).
    """
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise DraftError(f"응답 JSON 파싱 실패: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise DraftError(f"응답 JSON 파싱 실패: 객체가 아님({type(data).__name__})")
    try:
        draft = CuHintDraft.model_validate(data)
    except ValidationError as exc:
        locs = sorted({".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()})
        raise DraftError(f"응답 스키마 위반: {type(exc).__name__} ({', '.join(locs)})") from exc
    if answer is not None:
        norm_answer = _norm(answer)
        if len(norm_answer) >= _MIN_ANSWER_CONTAIN_LEN and norm_answer in _norm(draft.concept_name):
            raise DraftError("응답 스키마 위반: 개념 이름에 정답 값이 들어 있다 (concept_name)")
    return draft


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
# 산출물 I/O — append 전용(이력)은 줄마다 flush, 현재 상태(채택본·문맥)는 원자적 교체
# ──────────────────────────────────────────────────────────────────────────
def _append_lines(path: Path, lines: Sequence[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
            handle.flush()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """원자적 교체 — 같은 폴더 임시 파일에 쓰고 fsync 뒤 `os.replace`(중간 상태 노출 0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _atomic_write_lines(path: Path, lines: Sequence[str]) -> None:
    _atomic_write_bytes(path, "".join(line + "\n" for line in lines).encode("utf-8"))


def _hint_line(hint: Hint) -> str:
    return hint.model_dump_json()


def _is_json_object_line(raw: bytes) -> bool:
    try:
        return isinstance(json.loads(raw.decode("utf-8")), dict)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _quarantine_damaged_lines(path: Path) -> int:
    """append 전용 파일의 손상 줄을 `<이름>.corrupt`로 옮겨 보존하고 본 파일에서 걷어낸다.

    손상 = ① 개행 없이 끝난 마지막 줄(쓰는 도중 끊김 — 다음 append가 그 뒤에 붙으면 두 레코드가 한
    줄로 섞여 **영구 손상 행**이 된다) ② JSON 객체로 읽히지 않는 줄. 정상 줄은 바이트 그대로 남긴다.
    보존 파일은 append라 같은 손상이 여러 번 생겨도 앞의 증거를 덮지 않는다. 돌려주는 값은 옮긴 줄
    수다.
    """
    if not path.is_file():
        return 0
    data = path.read_bytes()
    if not data:
        return 0
    parts = data.split(b"\n")
    tail = parts.pop()  # 마지막 개행 뒤 조각 — 정상이면 빈 바이트
    keep: list[bytes] = []
    bad: list[bytes] = []
    for part in parts:
        if not part.strip():
            continue
        (keep if _is_json_object_line(part) else bad).append(part)
    if tail.strip():
        bad.append(tail)
    if not bad:
        return 0
    corrupt = path.with_name(path.name + ".corrupt")
    with corrupt.open("ab") as handle:
        for part in bad:
            handle.write(part + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    _atomic_write_bytes(path, b"".join(part + b"\n" for part in keep))
    _LOGGER.warning("%s 손상 줄 %d개를 %s로 격리", path.name, len(bad), corrupt.name)
    return len(bad)


# ──────────────────────────────────────────────────────────────────────────
# 재개 상태 — CU별 현재 채택본·시도 회계
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _CuState:
    """CU 1건의 현재 상태 — 채택본(문맥 행 + 통과 힌트 줄)과 누적 시도 회계(이력 파일에서 셈)."""

    context: dict[str, Any] | None = None
    hint_lines: list[str] = field(default_factory=list)
    attempts: int = 0
    gated_attempts: int = 0
    rejected_hints: int = 0

    @property
    def verified_levels(self) -> frozenset[int]:
        if self.context is None:
            return frozenset()
        return frozenset(self.context.get("verified_levels") or [])

    @property
    def complete(self) -> bool:
        return self.verified_levels >= frozenset(HINT_LEVELS)


@dataclass
class _ResumeState:
    cu: dict[uuid.UUID, _CuState] = field(default_factory=dict)
    discarded_inconsistent_rows: int = 0
    quarantined_genlog: int = 0
    quarantined_rejected: int = 0
    quarantined_state: int = 0
    removed_tmp: int = 0
    restored_from_backup: bool = False
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


def _load_contexts(
    path: Path, known: set[uuid.UUID], errors: list[str]
) -> dict[uuid.UUID, dict[str, Any]]:
    contexts: dict[uuid.UUID, dict[str, Any]] = {}
    if not path.is_file():
        return contexts
    rows, errs = _read_jsonl(path)
    errors.extend(errs)
    for line_no, _raw, row in rows:
        try:
            pid = uuid.UUID(str(row.get("problem_id")))
        except ValueError as exc:
            errors.append(f"{CONTEXT_FILE}:{line_no} problem_id 손상 — {type(exc).__name__}")
            continue
        verified = _levels(row.get("verified_levels"))
        rejected = _levels(row.get("rejected_levels"))
        if (
            pid not in known
            or pid in contexts
            or verified is None
            or rejected is None
            or not isinstance(row.get("generator_version"), str)
        ):
            errors.append(f"{CONTEXT_FILE}:{line_no} 알 수 없는 CU·중복·레벨·판 손상")
            continue
        if verified | rejected != frozenset(HINT_LEVELS) or verified & rejected:
            errors.append(f"{CONTEXT_FILE}:{line_no} 레벨 판정이 L1·L2·L3를 나누지 않는다")
            continue
        contexts[pid] = row
    return contexts


def _load_resume_state(
    run_dir: Path, cus: Sequence[CuInput], *, quarantine_state: bool = False
) -> _ResumeState:
    """기존 산출물 → CU별 채택본·누적 시도. 이력 파일 손상 줄은 격리, 상태 파일 손상은 오류."""
    state = _ResumeState(cu={cu.problem_id: _CuState() for cu in cus})
    known = set(state.cu)
    by_slug = {cu.slug: cu.problem_id for cu in cus}
    # ⓪ 끊긴 쓰기의 흔적 — 미완성 임시 파일은 버리고, 교체 도중 끊겼으면 직전 정합 상태로 되돌린다.
    state.removed_tmp = _remove_leftover_tmp(run_dir)
    try:
        state.restored_from_backup = _restore_interrupted_state(run_dir)
    except (OSError, ValueError) as exc:
        state.errors.append(f"{STATE_BACKUP_FILE} 복원 실패 — {type(exc).__name__}")
        return state
    # ① append 전용 이력 파일은 append 전에 손상 줄부터 격리한다(영구 손상 행 0).
    state.quarantined_genlog = _quarantine_damaged_lines(run_dir / GENLOG_FILE)
    state.quarantined_rejected = _quarantine_damaged_lines(run_dir / REJECTED_FILE)
    if quarantine_state:
        # 복구 스위치(런북 [R]) — 원자적 교체로만 쓰는 두 상태 파일이 외부에서 깨졌을 때만
        # 쓴다. 깨진 줄은 `.corrupt`로 보존되고, 짝을 잃은 CU는 아래 정합 검사가 걷어내 다시 만든다.
        state.quarantined_state = _quarantine_damaged_lines(
            run_dir / HINTS_FILE
        ) + _quarantine_damaged_lines(run_dir / CONTEXT_FILE)
    # ② 시도 회계 — 생성 로그의 그 CU 행 수가 총 시도, success 행 수가 게이트 도달 시도다.
    genlog_path = run_dir / GENLOG_FILE
    if genlog_path.is_file():
        rows, errs = _read_jsonl(genlog_path)
        state.errors.extend(errs)
        for line_no, _raw, row in rows:
            pid = by_slug.get(str(row.get("cu_slug")))
            if pid is None:
                state.errors.append(f"{GENLOG_FILE}:{line_no} cu.jsonl에 없는 CU의 시도 기록")
                continue
            state.cu[pid].attempts += 1
            if row.get("success") is True:
                state.cu[pid].gated_attempts += 1
    for _raw, hint in _load_hint_rows(
        run_dir / REJECTED_FILE, verified=False, known=known, errors=state.errors
    ):
        state.cu[hint.solution_step_ref.problem_id].rejected_hints += 1
    # ③ 현재 상태 — 문맥 행 + 채택본 힌트 줄. 둘이 어긋난 CU는 걷어낸다.
    contexts = _load_contexts(run_dir / CONTEXT_FILE, known, state.errors)
    accepted = _load_hint_rows(
        run_dir / HINTS_FILE, verified=True, known=known, errors=state.errors
    )
    if state.errors:
        return state
    grouped: dict[uuid.UUID, list[tuple[str, Hint]]] = {}
    for raw, hint in accepted:
        grouped.setdefault(hint.solution_step_ref.problem_id, []).append((raw, hint))
    dropped = False
    for pid, st in state.cu.items():
        ctx = contexts.get(pid)
        cu_rows = grouped.get(pid, [])
        levels = [h.level for _, h in cu_rows]
        consistent = (
            ctx is not None
            and len(levels) == len(set(levels))
            and frozenset(levels) == frozenset(ctx["verified_levels"])
            and all(h.generator_version == ctx["generator_version"] for _, h in cu_rows)
        )
        if consistent:
            st.context = ctx
            st.hint_lines = [raw for raw, _ in cu_rows]
        elif ctx is not None or cu_rows:
            # 원자적 교체 두 번 사이에서 끊겼다 — 어느 쪽도 믿지 않고 미완으로 다시 만든다.
            state.discarded_inconsistent_rows += len(cu_rows) + (1 if ctx is not None else 0)
            dropped = True
    if dropped:
        _write_current_state(run_dir, cus, state.cu)
    return state


def _write_current_state(
    run_dir: Path, cus: Sequence[CuInput], cu_states: Mapping[uuid.UUID, _CuState]
) -> None:
    """현재 채택본 전체를 두 파일에 쓴다 — 두 파일을 **하나의 교체 단위**로 묶는다.

    순서: ① 직전 두 파일 내용을 보존본(`STATE_BACKUP_FILE`)에 원자적으로 쓴다 ② 문맥 → ③ 채택본
    힌트를 각각 원자적으로 교체한다 ④ 보존본을 지운다(**커밋 지점**). ①~④ 사이 어디서 끊겨도
    보존본이 남으므로, 다음 실행의 `_restore_interrupted_state`가 두 파일을 직전 정합 상태로
    되돌린다(새 채택본은 잃지만 생성 로그·거부 이력은 남고, 그 CU는 남은 예산 안에서 다시 만든다).
    보존본 쓰기 자체가 끊기면(①) 두 파일은 손대지 않은 상태다.
    """
    hint_lines = [line for cu in cus for line in cu_states[cu.problem_id].hint_lines]
    context_lines = [
        json.dumps(cu_states[cu.problem_id].context, ensure_ascii=False)
        for cu in cus
        if cu_states[cu.problem_id].context is not None
    ]
    backup = {
        "context": _read_text_or_none(run_dir / CONTEXT_FILE),
        "hints": _read_text_or_none(run_dir / HINTS_FILE),
    }
    _atomic_write_bytes(
        run_dir / STATE_BACKUP_FILE, json.dumps(backup, ensure_ascii=False).encode("utf-8")
    )
    _atomic_write_lines(run_dir / CONTEXT_FILE, context_lines)
    _atomic_write_lines(run_dir / HINTS_FILE, hint_lines)
    (run_dir / STATE_BACKUP_FILE).unlink()


def _read_text_or_none(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _restore_interrupted_state(run_dir: Path) -> bool:
    """보존본이 남아 있으면(교체 도중 끊김) 두 상태 파일을 직전 정합 상태로 되돌리고 보존본을
    지운다.

    복원 도중 다시 끊겨도 보존본은 마지막에 지우므로 다음 실행이 같은 복원을 다시 한다(멱등).
    보존본이 JSON으로 읽히지 않으면 예외가 올라가 입력 오류로 멈춘다 — 원자적으로 쓴 파일이라 정상
    경로에서는 없다.
    """
    backup_path = run_dir / STATE_BACKUP_FILE
    if not backup_path.is_file():
        return False
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    for name, key in ((CONTEXT_FILE, "context"), (HINTS_FILE, "hints")):
        previous = backup.get(key)
        if previous is None:
            (run_dir / name).unlink(missing_ok=True)
        else:
            _atomic_write_bytes(run_dir / name, str(previous).encode("utf-8"))
    backup_path.unlink()
    _LOGGER.warning("채택본 교체 도중 끊긴 흔적 — 보존본으로 직전 정합 상태를 복원했다")
    return True


def _remove_leftover_tmp(run_dir: Path) -> int:
    """끊긴 원자적 쓰기가 남긴 `<파일>.tmp`를 지운다 — 완성되지 않은 쓰기라 내용은 버린다(원본은
    그대로다)."""
    removed = 0
    for name in (HINTS_FILE, CONTEXT_FILE, GENLOG_FILE, REJECTED_FILE, STATE_BACKUP_FILE):
        tmp = run_dir / (name + ".tmp")
        if tmp.is_file():
            tmp.unlink()
            removed += 1
    return removed


# ──────────────────────────────────────────────────────────────────────────
# 리포트
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class PassReport:
    """패스 1회 정직 회계 — 수치는 전부 실측(조용한 생략 0). `*_total`은 이전 실행 누적 포함."""

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
    budget_exhausted_cus: list[str] = field(default_factory=list)
    complete_cus: int = 0
    measurable_cus: int = 0
    hints_generated: int = 0
    verified_by_level: Counter[int] = field(default_factory=Counter)
    """이번 실행에서 새로 채택된 힌트의 레벨 분포(THIS_RUN_*)."""
    total_verified_by_level: Counter[int] = field(default_factory=Counter)
    """채택본 파일 기준 누적 레벨 분포(TOTAL_*) — 판정은 이 값으로 한다."""
    rejected_by_gate: Counter[str] = field(default_factory=Counter)
    stopped_reason: str = ""
    removed_tmp: int = 0
    restored_from_backup: int = 0
    failure_kinds: Counter[str] = field(default_factory=Counter)
    routes: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    cu_attempts: dict[str, int] = field(default_factory=dict)
    cu_gated_attempts: dict[str, int] = field(default_factory=dict)
    rejected_hints_total: int = 0
    discarded_inconsistent_rows: int = 0
    quarantined_genlog: int = 0
    quarantined_rejected: int = 0
    quarantined_state: int = 0
    genlog_errors: int = 0

    @property
    def exit_code(self) -> int:
        if self.input_errors:
            return EXIT_INPUT_ERROR
        if self.failed_cus or self.incomplete_cus or self.pending_cus or self.genlog_errors:
            return EXIT_INCOMPLETE
        return EXIT_OK

    @property
    def gate_reject_rate(self) -> float | None:
        """게이트 거부율 = 거부 힌트 ÷ (게이트 도달 시도 × 3) — 누적. 분모 0이면 None(날조 금지)."""
        gated = sum(self.cu_gated_attempts.values())
        return self.rejected_hints_total / (gated * len(HINT_LEVELS)) if gated else None

    def render_lines(self) -> list[str]:
        """요약 `KEY=VALUE` 줄 — 마지막 줄은 항상 `EXIT=<n>`."""

        def j(value: object) -> str:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)

        by_level = {f"L{k}": v for k, v in sorted(self.verified_by_level.items())}
        total_by_level = {f"L{k}": v for k, v in sorted(self.total_verified_by_level.items())}
        rate = self.gate_reject_rate
        regenerated = sorted(s for s, n in self.cu_gated_attempts.items() if n > 1)
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
            f"CU_BUDGET_EXHAUSTED={len(self.budget_exhausted_cus)}",
            f"CU_REGENERATED={len(regenerated)}",
            f"CALLS={self.calls}",
            f"CALLS_FAILED={self.calls_failed}",
            f"CALL_FAILURE_KINDS={j(dict(self.failure_kinds))}",
            f"ROUTES={j(dict(self.routes))}",
            f"MODELS={j(dict(self.models))}",
            f"HINT_ATTEMPTS_THIS_RUN={self.calls}",
            f"HINT_ATTEMPTS_TOTAL={sum(self.cu_attempts.values())}",
            f"HINT_GATED_ATTEMPTS_TOTAL={sum(self.cu_gated_attempts.values())}",
            f"HINT_GATE_REJECTED_HINTS_TOTAL={self.rejected_hints_total}",
            f"HINT_GATE_REJECT_RATE={'None' if rate is None else f'{rate:.4f}'}",
            f"CU_ATTEMPTS={j(self.cu_attempts)}",
            f"THIS_RUN_HINTS_GATED={self.hints_generated}",
            f"THIS_RUN_HINTS_VERIFIED={sum(self.verified_by_level.values())}",
            f"THIS_RUN_VERIFIED_BY_LEVEL={j(by_level)}",
            f"THIS_RUN_REJECTED_BY_GATE={j({g: self.rejected_by_gate[g] for g in GATE_NAMES})}",
            f"TOTAL_HINTS_VERIFIED={sum(self.total_verified_by_level.values())}",
            f"TOTAL_VERIFIED_BY_LEVEL={j(total_by_level)}",
            f"RESUME_REMOVED_TMP={self.removed_tmp}",
            f"RESUME_RESTORED_FROM_BACKUP={self.restored_from_backup}",
            f"RESUME_DISCARDED_INCONSISTENT_ROWS={self.discarded_inconsistent_rows}",
            f"GENLOG_QUARANTINED_LINES={self.quarantined_genlog}",
            f"REJECTED_QUARANTINED_LINES={self.quarantined_rejected}",
            f"STATE_QUARANTINED_LINES={self.quarantined_state}",
            f"GENLOG_WRITE_ERRORS={self.genlog_errors}",
        ]
        lines.extend(f"INPUT_ERROR={e}" for e in self.input_errors)
        lines.append(f"FAILED_CUS={','.join(self.failed_cus)}")
        lines.append(f"INCOMPLETE_CUS={','.join(self.incomplete_cus)}")
        lines.append(f"BUDGET_EXHAUSTED_CUS={','.join(self.budget_exhausted_cus)}")
        lines.append(f"REGENERATED_CUS={','.join(regenerated)}")
        lines.append(f"PENDING_CUS={','.join(self.pending_cus)}")
        lines.append(f"PASS_STOPPED={self.stopped_reason}")
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


def _http_status(exc: BaseException) -> int | None:
    """예외에 붙은 HTTP 상태코드(비내용 필드) — `status_code`·`status`·`response.status_code`."""
    candidates = (
        getattr(exc, "status_code", None),
        getattr(exc, "status", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    )
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def _safe_exc_summary(exc: BaseException) -> str:
    """예외 요약 — `<타입명>` 또는 `<타입명>(HTTP nnn)`. **원문(str(exc))은 싣지 않는다.**

    원문에는 요청 URL·헤더 조각·응답 본문(때로 키 접두)이 섞일 수 있고, 생성 로그는 산출물 브랜치로
    원격에 올라간다. 이 함수는 **절대 예외를 던지지 않는다** — 속성 접근이 실패하면 타입명만, 그마저
    실패하면 고정 문자열로 접는다(같은 의미의 공용 함수는 EOS-212가 정리한다).
    """
    try:
        name = type(exc).__name__
        status = _http_status(exc)
        return f"{name}(HTTP {status})" if status is not None else name
    except Exception:  # noqa: BLE001 — 요약 함수가 실패 경로를 깨면 안 된다
        try:
            return type(exc).__name__
        except Exception:  # noqa: BLE001
            return "UnknownError"


def _record_trace(call: _CallContext, decision: RoutingDecision, result: GenerationResult) -> None:
    """Langfuse 관측(응답을 받은 호출) — never-break, 실패는 예외 타입명을 남긴다."""
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
    attempt_id: uuid.UUID,
    cu: CuInput,
    prompt: str,
    decision: RoutingDecision,
    result: GenerationResult | None,
    seed: int | None,
    error_detail: str | None,
) -> bool:
    """시도 1건 → `GenerationLog` 1행 즉시 append(log_id = 시도 ID). 기록 실패면 False(타입명
    로그)."""
    usage = result.usage if result is not None else None
    try:
        model_name = model_name_for_decision(decision, settings=call.settings)
        seat = None if _is_local(decision) else cloud_provider_name(call.settings)
        latency = int(round(usage.latency_ms)) if usage and usage.latency_ms is not None else None
        log = GenerationLog(
            log_id=attempt_id,
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
        append_generation_log_jsonl(call.genlog_path, log, run_id=call.run_id)
        report.models[model_name] += 1
        return True
    except Exception as exc:  # noqa: BLE001 — 기록 실패를 삼키지 않는다(회계 + 타입명 + 정지)
        report.genlog_errors += 1
        _LOGGER.warning(
            "CU 힌트 생성 로그 기록 실패(%s) — 패스를 멈춘다(종료 코드 1)", type(exc).__name__
        )
        return False


class _GenlogWriteStoppedError(Exception):
    """생성 로그를 쓰지 못했다 — 기록 없는 호출을 더 하지 않도록 패스를 멈추는 내부 신호.

    기록이 없으면 그 시도는 예산 회계(생성 로그 행 수)에서 빠져 다음 실행이 같은 CU를 다시
    부른다(유료 좌석이면 과금 누수). "실패해도 증거가 남아야 한다"는 측정 도구 규칙상 증거를 남길
    수 없는 상태에서는 호출을 계속하지 않는다.
    """


async def _attempt(
    call: _CallContext, report: PassReport, cu: CuInput, prompt: str
) -> tuple[CuHintDraft | None, RoutingDecision, uuid.UUID]:
    """라우터 결정 → 호출 → 파싱 → 로그 1행. (계약 또는 None, 결정, 시도 ID)."""
    attempt_id = uuid.uuid4()
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

    def log(result: GenerationResult | None, error_detail: str | None) -> None:
        if not _emit_genlog(
            call,
            report,
            attempt_id=attempt_id,
            cu=cu,
            prompt=prompt,
            decision=decision,
            result=result,
            seed=seed,
            error_detail=error_detail,
        ):
            raise _GenlogWriteStoppedError

    try:
        result = await call.provider.generate(prompt, CU_HINT_SYSTEM, decision, **kwargs)
    except Exception as exc:  # noqa: BLE001 — provider 장애는 재시도 대상(타입명만 기록)
        report.calls_failed += 1
        report.failure_kinds["provider"] += 1
        detail = f"provider.generate failed: {_safe_exc_summary(exc)}"
        _LOGGER.warning("CU 힌트 provider 호출 실패(%s) — %s", _safe_exc_summary(exc), cu.slug)
        log(None, detail)
        return None, decision, attempt_id
    _record_trace(call, decision, result)
    try:
        draft = parse_draft(result.text, answer=cu.answer)
    except DraftError as exc:
        report.calls_failed += 1
        report.failure_kinds["parse" if "파싱" in exc.detail else "schema"] += 1
        _LOGGER.warning("CU 힌트 응답 거부(%s) — %s", exc.detail, cu.slug)
        log(result, exc.detail)
        return None, decision, attempt_id
    log(result, None)
    return draft, decision, attempt_id


# ──────────────────────────────────────────────────────────────────────────
# 게이트 → 후보
# ──────────────────────────────────────────────────────────────────────────
def _adoption_key(candidate: _Candidate) -> tuple[bool, int, int]:
    """채택 순위 — ① L1·L2를 둘 다 통과했는가(측정기가 그 CU를 판정할 수 있는가) ② 통과 레벨 수 ③
    나중 시도.

    ①이 첫 키인 이유: {L1,L3}와 {L1,L2}는 통과 수가 같지만, 측정기(무관용 L1·L2)는 앞의 것을
    판정하지 못해 UNDECIDED를 낸다. 통과 수만 보면 나중 시도 {L1,L3}가 측정 가능한 {L1,L2}를
    밀어낸다.
    """
    return (_MEASURABLE_LEVELS <= candidate.verified, len(candidate.verified), candidate.order)


_MEASURABLE_LEVELS: Final[frozenset[int]] = frozenset({1, 2})


@dataclass
class _Candidate:
    """게이트까지 간 시도 1건 — 채택 후보(통과 힌트·문맥 행)."""

    accepted: list[Hint]
    context: dict[str, Any]
    order: int  # 채택 동점일 때 나중 것을 고르는 순번(이전 실행 채택본 = -1)

    @property
    def verified(self) -> frozenset[int]:
        return frozenset(self.context["verified_levels"])

    @property
    def complete(self) -> bool:
        return self.verified >= frozenset(HINT_LEVELS)


def _gate(
    run_dir: Path,
    report: PassReport,
    cu: CuInput,
    draft: CuHintDraft,
    *,
    value_exposure: AnswerValueExposure | None,
    generator_version: str,
    order: int,
    extra: Mapping[str, object],
) -> _Candidate:
    """게이트 3종 → 거부분은 이력 파일에 즉시 append → 채택 후보(아직 현재 상태에 쓰지 않는다)."""
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
    for hint in rejected:
        for gate in GATE_NAMES:
            verdict = hint.gate_report.get(gate)
            if not (isinstance(verdict, dict) and verdict.get("passed") is True):
                report.rejected_by_gate[gate] += 1
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
    return _Candidate(accepted=accepted, context=context_row, order=order)


def _tally(report: PassReport, cu: CuInput, verified: frozenset[int]) -> None:
    """CU 상태 회계 — 완료(L1·L2·L3 verified)·측정 가능(L1·L2 verified)·미완."""
    if verified >= {1, 2}:
        report.measurable_cus += 1
    if verified >= set(HINT_LEVELS):
        report.complete_cus += 1
    else:
        report.incomplete_cus.append(cu.slug)


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
    redo_incomplete: bool = False,
    quarantine_damaged_state: bool = False,
    subscription: str | None = None,
    budget_krw: float | None = None,
    temperature: float = _DEFAULT_TEMPERATURE,
    seed_source: SeedSource | None = None,
    run_id: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> PassReport:
    """회차 폴더 1개에 사후 힌트 패스를 돈다.

    `value_exposure`는 필수 키워드다(None = 값 축 fail-closed). 입력 오류가 있으면 LLM을 한 번도
    부르지 않고 리포트만 돌려준다(종료 코드 2). 시도 예산·재개·선택 규칙은 모듈 docstring.
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
    state = _load_resume_state(run_dir, cus, quarantine_state=quarantine_damaged_state)
    report.quarantined_genlog = state.quarantined_genlog
    report.quarantined_rejected = state.quarantined_rejected
    report.quarantined_state = state.quarantined_state
    if state.errors:
        report.input_errors.extend(state.errors)
        return report
    report.discarded_inconsistent_rows = state.discarded_inconsistent_rows
    report.removed_tmp = state.removed_tmp
    report.restored_from_backup = int(state.restored_from_backup)

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
    budget = retries + 1

    for cu in cus:
        st = state.cu[cu.problem_id]
        if st.complete:
            report.cu_resumed += 1
            _account(report, cu, st)
            _tally(report, cu, st.verified_levels)
            continue
        remaining = budget if redo_incomplete else budget - st.attempts
        if remaining <= 0:
            report.budget_exhausted_cus.append(cu.slug)
            _account(report, cu, st)
            if st.context is None:
                report.failed_cus.append(cu.slug)
            else:
                _tally(report, cu, st.verified_levels)
            continue
        if report.stopped_reason or (limit is not None and report.cu_processed >= limit):
            report.pending_cus.append(cu.slug)
            _account(report, cu, st)
            continue
        report.cu_processed += 1
        try:
            best = await _run_cu(
                run_dir,
                call,
                report,
                cu,
                st,
                remaining=remaining,
                value_exposure=value_exposure,
            )
        except _GenlogWriteStoppedError:
            # 기록 없는 시도의 결과는 채택하지 않는다 — 이 CU는 직전 상태 그대로 미처리로 남긴다.
            report.stopped_reason = "genlog_write_failed"
            report.pending_cus.append(cu.slug)
            _account(report, cu, st)
            _progress(call, f"PASS_STOPPED reason=genlog_write_failed slug={cu.slug}")
            continue
        if best is not None and best.order >= 0:
            st.context = best.context
            st.hint_lines = [_hint_line(h) for h in best.accepted]
        if st.context is not None:
            # 누적 시도 회계를 채택본 문맥 행에 싣는다(이전 채택본이 남아도 회계는 최신).
            st.context = {
                **st.context,
                "attempts_total": st.attempts,
                "gated_attempts_total": st.gated_attempts,
                "rejected_hints_total": st.rejected_hints,
            }
            _write_current_state(run_dir, cus, state.cu)
        _account(report, cu, st)
        if st.context is None:
            report.failed_cus.append(cu.slug)
            _progress(call, f"CU_FAILED slug={cu.slug} attempts_total={st.attempts}")
            continue
        _tally(report, cu, st.verified_levels)
        _progress(
            call,
            f"CU_DONE slug={cu.slug} verified_levels={sorted(st.verified_levels)} "
            f"attempts_total={st.attempts} gated_attempts_total={st.gated_attempts} "
            f"processed={report.cu_processed}",
        )

    flush = getattr(trace, "flush", None)
    if callable(flush):
        try:
            flush()
        except Exception as exc:  # noqa: BLE001 — 전송 확정 실패가 결과를 깨면 안 된다(타입명 로그)
            _LOGGER.warning("CU 힌트 패스 관측 flush 실패(%s)", type(exc).__name__)
    return report


def _account(report: PassReport, cu: CuInput, st: _CuState) -> None:
    report.cu_attempts[cu.slug] = st.attempts
    report.cu_gated_attempts[cu.slug] = st.gated_attempts
    report.rejected_hints_total += st.rejected_hints
    for level in st.verified_levels:
        report.total_verified_by_level[level] += 1


async def _run_cu(
    run_dir: Path,
    call: _CallContext,
    report: PassReport,
    cu: CuInput,
    st: _CuState,
    *,
    remaining: int,
    value_exposure: AnswerValueExposure | None,
) -> _Candidate | None:
    """CU 1건의 시도 루프 — 세 레벨 통과면 멈추고, 아니면 예산 안에서 다시 만든다. 채택 후보를 낸다.

    게이트 거부도 시도 1회를 쓴다(provider·파싱·계약 실패와 같은 예산). 채택 규칙: 세 레벨 통과가
    나오면 그것, 아니면 통과 레벨 수가 가장 많은 후보(동점이면 나중 것 · 이전 실행 채택본도 후보
    `order=-1`).
    """
    prompt = build_cu_hint_user(
        question=cu.question,
        answer=cu.answer,
        explanation=cu.explanation,
        subject=cu.subject,
        standards=cu.standards,
    )
    candidates: list[_Candidate] = []
    if st.context is not None:
        prior_hints = [Hint.model_validate_json(line) for line in st.hint_lines]
        candidates.append(_Candidate(accepted=prior_hints, context=st.context, order=-1))
    for order in range(remaining):
        draft, decision, attempt_id = await _attempt(call, report, cu, prompt)
        st.attempts += 1
        if draft is None:
            continue
        st.gated_attempts += 1
        generator_version = (
            f"{CU_HINT_GENERATOR_VERSION}@{call.prompt_version}#{attempt_id.hex[:12]}"
        )
        candidate = _gate(
            run_dir,
            report,
            cu,
            draft,
            value_exposure=value_exposure,
            generator_version=generator_version,
            order=order,
            extra={
                "prompt_version": call.prompt_version,
                "route": _route_label(decision),
                "attempt_id": str(attempt_id),
                "attempt_no": st.attempts,
                "run_id": call.run_id,
            },
        )
        st.rejected_hints += len(candidate.context["rejected_levels"])
        candidates.append(candidate)
        if candidate.complete:
            break
    if not candidates:
        return None
    best = max(candidates, key=_adoption_key)
    if best.order >= 0:
        for hint in best.accepted:
            report.verified_by_level[hint.level] += 1
    return best


# ──────────────────────────────────────────────────────────────────────────
# CLI 본체 — 프로세스 시작점(`harness/cu_hint_pass.py`)이 provider·관측·값 축 능력을 내려 준다
# ──────────────────────────────────────────────────────────────────────────
def build_arg_parser(prog: str) -> argparse.ArgumentParser:
    """CLI 인자 — 저작 CLI(`problem_corpus_accumulate`)의 좌석 신호와 같은 이름을 쓴다."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "저장된 CU에 LLM으로 단계 목록과 L1·L2·L3 힌트를 붙이고 게이트 3종 통과분만 verified로 "
            "내보낸다(EOS-211). exit 0=전 CU 완료 · 1=일부 미완 · 2=입력 오류 · "
            "3=처리되지 않은 예외."
        ),
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="회차 좌석 폴더(cu.jsonl 보유)")
    parser.add_argument(
        "--retries",
        type=int,
        default=_DEFAULT_RETRIES,
        help="CU당 총 시도 상한 = retries+1(첫 시도부터 누적 · 게이트 거부 재생성 포함 · 기본 2)",
    )
    parser.add_argument("--limit", type=int, default=None, help="이번 실행에서 새로 처리할 CU 상한")
    parser.add_argument(
        "--redo-incomplete",
        action="store_true",
        help="시도 예산이 떨어진 미완 CU에도 이번 실행에서 예산을 새로 준다(이력은 보존)",
    )
    parser.add_argument(
        "--quarantine-damaged-state",
        action="store_true",
        help=(
            "복구용 — 채택본·문맥 파일의 깨진 줄을 .corrupt로 옮기고 짝을 잃은 CU를 다시 만든다"
            "(기본은 입력 오류 2로 멈춘다)"
        ),
    )
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
    value_exposure_factory: Callable[[], AnswerValueExposure | None],
) -> int:
    """인자 해석 → 패스 → 요약 출력 → 종료 코드. provider는 인자 검증 *뒤에* 만든다.

    세 의존(provider·관측·값 축 능력)은 모두 try **안에서** 만든다 — 조립 단계의 예외도 exit 3으로
    드러난다. 처리되지 않은 예외는 여기서 잡아 `UNHANDLED_ERROR=<타입명>`·`EXIT=3`으로 낸다 —
    1(미완)과 섞이면 "일부 CU 미완"과 "디스크가 꽉 찼다"가 같은 신호가 된다. 원문은 싣지
    않는다(타입명만).
    """
    args = build_arg_parser(prog).parse_args(list(argv) if argv is not None else None)
    try:
        report = asyncio.run(
            run_cu_hint_pass(
                args.run_dir,
                provider=provider_factory(),
                value_exposure=value_exposure_factory(),
                trace=trace_factory(),
                retries=args.retries,
                limit=args.limit,
                redo_incomplete=bool(args.redo_incomplete),
                quarantine_damaged_state=bool(args.quarantine_damaged_state),
                subscription=args.subscription,
                budget_krw=args.budget_krw,
                on_progress=lambda line: print(line, flush=True),
                temperature=args.temperature,
            )
        )
    except Exception as exc:  # noqa: BLE001 — 최상위: 미분류 예외를 별도 종료 코드로 드러낸다
        summary = _safe_exc_summary(exc)
        _LOGGER.error("CU 힌트 패스 처리되지 않은 예외(%s)", summary)
        print(f"UNHANDLED_ERROR={summary}\nEXIT={EXIT_UNHANDLED}", flush=True)
        return EXIT_UNHANDLED
    print("\n".join(report.render_lines()))
    return report.exit_code
