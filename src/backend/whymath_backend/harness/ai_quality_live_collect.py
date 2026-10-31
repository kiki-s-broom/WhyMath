"""P3-78 — AI 품질 8종 라이브 후보 수집: 평가 사례마다 WH-1 primary 러너를 돌려 응답 JSONL을 만든다.

정본 지시: `backlog/tasks/P3-78-ai-quality-live-candidate-run.yaml` · 평가기 = `ai_quality_eval`
(`--responses <이 도구의 산출>`) · 보고서 =
`docs/reviews/p3_10_ai_quality_eval_suite_2026-10-21.md`.

사용
----
    python -m whymath_backend.harness.ai_quality_live_collect --out runs/p3_78/live.jsonl
    python -m whymath_backend.harness.ai_quality_live_collect --out runs/p3_78/live.jsonl --resume
    python -m whymath_backend.harness.ai_quality_live_collect --out smoke.jsonl --limit 3
    python -m whymath_backend.harness.ai_quality_eval --responses runs/p3_78/live.jsonl \\
        --json runs/p3_78/live.report.json

무엇을 부르는가
--------------
사례마다 `harness.wh1_primary.run_wh1_primary_turn`(코치 `_wh1_primary_decision_or`가 부르는 그
러너)을 한 번 돌린다. LLM 호출은 전부 러너 안의 `LLMTutorPolicy` → `Wh1LlmSeam` →
`l3.pipeline.generate`(`Router().route()` — 라우터 경유) → provider로 간다. 이 도구는 LLM을 직접
부르지 않는다. provider는 서빙과 같은 팩토리(`build_cloud_provider` + Ollama), 관측은 서빙과 같은
`LangfuseSink`로 조립한다(`ai_quality_live_seat`). 러너가 돌려준 발화는 코치와 같이 **승격 직전
재검증**(`check_deliverable`)을 거친다.

사례 → 러너 입력 — 코치 요청 처리를 그대로 옮긴다
-----------------------------------------------
- **선택 사례**(학생이 보기를 탭한 턴): 학생 앱(`ChatController.send`)은 탭한 보기의 *값
  문자열*을 `student_input`, 인덱스를 `selected_choice_index`로 보내고 **`solution_steps`·
  `student_solution`은 보내지 않는다**. 코치는 새 대화(`create_session`)로 받아 러너에
  `student_solution = student_solution or student_input`(= 보기 문자열), `solution_steps =
  solution_steps or []`(= 빈 목록), 턴 번호 1을 넘긴다. 단계 제출이 없으므로 하네스 verify 의무가
  없고 정답 억제 백스톱도 걸리지 않는다 — **정책이 쓴 발화가 그대로 학생에게 갈 수 있다**(이 도구도
  똑같이 그렇다). 완료 상태머신은 마지막 풀이 단계가 없어 개입하지 않는다
  (`_last_solution_step` = None).
- **힌트 사례**(대화 중 막힌 턴 — `append_turns`): 학생 발화 = 사례 신호 문장, 풀이 단계 = 없음,
  Polya 상태 = 신호의 `turn_count`·`prev_hint_level`, 턴 번호 = `turn_count + 1`(같은 단계의 직전
  교환이 `turn_count`번 있었던 가장 짧은 대화 — `total_turns // 2 + 1`).
- **초기 가설**: 코치의 두 채널을 같은 함수로 재현한다 — 텍스트 채널(`misconception_semantic_mode
  ="off"` 경로: `diagnose` → `reject_refuted` → `apply_match_quality_gate`, 보류 판정이면 비움) +
  선지 채널(`l4_distractor_link_enabled`면 `distractor_link_matches`) → 코치 `_merge_distractor_
  matches`와 같은 규칙(이미 있는 id 제외·뒤에 붙임) → 처음 보는 학생의 큐레이션 `curate([], …)`.
  (2026-10-31 실측: 244사례 전부 결정론 후보의 `case_hypotheses`와 같다 — 텍스트 채널은 0건 발동.)
- **힌트 단계**: Polya 엔진과 같은 `decide_hint_level(student_input, turn_count, prev_hint_level)`
  (숙달 라벨 없음 — 처음 보는 학생).
- **튜터 내용 요약**: 개념(code = 사례 `concept_id`, 이름 = 레지스트리 `name_ko`) + 문제 구조
  (`ProblemBrief` — 적재기 `load_problem_bank_records`로 코퍼스 행을 `Problem`으로 검증한 뒤 코치
  `_problem_brief_for`와 같은 변환: 발문 형식·Bloom·시각자료·조건 수 ≤ 20).
- **미공급(DB 조회 슬롯 — 평가셋에 재료가 없다)**: 스킬 이름, 교수법 팩(`pack` — 개념 k_type은
  DB 조회라 없음 → 금지모드 가드 블록은 **돌지 않는다**), 튜터 context 매니페스트
  (`tutor_context`), `session`(select_probe 후보 공급 — 후보 0), `session_recall`·웜스타트
  outside_mids(처음 보는 학생이라 서빙에서도 비어 있을 값), θ·학년·숙달. `run.json`의
  `supplied`/`unsupplied`가 같은 목록을 싣는다.
- **재현하지 않는 설정 분기**: `misconception_semantic_mode`가 off가 아니거나 `misconception_judge_
  enabled`면 코치의 텍스트 채널이 달라진다 — 이 도구는 off 경로만 재현하고 `run.json`
  `unreproduced`에 그 사실을 적는다.

결정론 후보(`eos-deterministic`)와 같은 것 / 다른 것
-------------------------------------------------
**같은 것** — 구조체 빌더(`build_tutor_output`)와 서버 측 재료: 검증 판정 = 사례 라벨
(`case.verdict` — 코치의 답 판정에 해당), 진단 = 위 초기 가설(결정론 후보와 같은 값), 개념 = 사례
`concept_id`, `referenced_concept_ids` = 빈 튜플(러너는 도구 트레이스를 돌려주지 않는다).
**다른 것** — 러너가 서빙한 구조체의 세 필드: 발화 본문(`explanation`), 발화 저자
(`explanation_source`), 응답 전략(`response_strategy` — 발화와 같은 `end_turn`에서 나오므로 발화만
바꾸면 모순 구조체가 된다). 다음 행동은 같은 빌더 규칙으로 따라 바뀐다. 힌트 단계는 엔진 값이다
(결정론 후보는 P3-77 L3 공백을 L2로 낮춰 표시한다). 사례 판정으로 재조립한 구조체를 P3-09가
거부하면 러너가 실제로 서빙한 구조체를 주석과 함께 싣는다.

사례 결말 — **라이브 = LLM이 쓴 발화가 학생 대면 본문으로 나간 턴**
---------------------------------------------------------------
러너 관측 레코드(`wh1_shadow.record_logger` — `primary_outcome`·`llm_output_rejections`)와 러너가
서빙한 구조체의 `explanation_source`로 가른다. 응답 파일의 `origin`이 결말을 말한다.

- `wh1-live` — `adopted` ∧ `explanation_source="llm"`(정책 명시 발화 또는 프로즈 rephrase).
- `wh1-live:harness` — `adopted`지만 본문이 하네스 파생 템플릿(LLM은 행위만 골랐다). **라이브로
  세지 않는다.**
- `wh1-live:degraded` — 정책의 안전 강등(`fallback_llm_degraded`) 또는 금지모드 가드. 원인을 나눈다:
  `output_schema`(관측 `llm_output_rejections > 0` — LLM 출력이 계약을 어겼다) · `mode_guard` ·
  `unknown`(관측만으로는 원인 미상).
- `wh1-live:fallback` — 러너 `None`(예산 소진·발화 없음·프로즈 게이트·출력 스키마) 또는 승격 재검증
  거부 → 서빙처럼 결정론 폴백 = 이 사례의 `eos-deterministic` 응답.
- `wh1-live:unclassified` — 발화는 돌아왔는데 관측 레코드가 없거나 어휘 밖.
- **실패(응답 파일에 쓰지 않는다)** — `provider_error`(provider 예외 — 정책이 강등으로 흡수해도) ·
  `pipeline_error`(provider 밖 파이프라인·라우터·캐시 예외를 정책이 흡수 — 정책 WARNING으로 식별) ·
  `runner_timeout`·`runner_exception`(러너가 삼킨 예외의 타입명·연쇄·메시지 일부를 러너 WARNING의
  `exc_info`에서 붙잡는다) · `outer_timeout` · `collector_error`. 응답이 없는 사례는 평가기가 "응답
  누락" 실패로 세고, `--resume`이 다시 돈다.

캐시·프롬프트 동일성 — 표본 독립성의 한계
-----------------------------------------
캐시는 **사례마다 새 `InMemoryCache`**다. 실행 전체가 한 캐시를 쓰면 같은 프롬프트의 사례가 앞 사례
응답을 재생해(2026-10-31 실측: 244사례에 provider 72회·적중 236회, 힌트 180건 중 발화 30종) 평가기가
재생본을 독립 표본으로 센다. 그러나 캐시를 끊어도 **정책 프롬프트는 문항 본문·학생 원문을 담지
않으므로**(P3-72 계약) 같은 개념·같은 신호·같은 문제 구조의 사례는 같은 프롬프트를 받고, 샘플링이
결정적이면 같은(또는 비슷한) 응답을 낸다. 그래서 사례마다 **첫 정책 프롬프트의 지문**(system +
prompt의 sha256 — 원문은 남기지 않는다)을 `run.json`에 남기고, **서로 다른 첫 프롬프트 수 = 유효
표본 상한**을 계산해 적는다. 축별 Wilson 판정은 이 상한을 함께 읽어야 한다.

산출물 3종
----------
- `<out>` — `ai-quality-response/v1` JSONL(`load_responses`로 그대로 읽힌다 · 메타 줄 없음).
  사례마다 즉시 한 줄 쓰고 flush·fsync한다.
- `<out>.failures.jsonl` — 실패 1건 1줄(실행 id · 사례 id · 종류 · 예외 타입명 연쇄 · HTTP 상태 ·
  본문/메시지 일부(300자·키 모양 문자열 가림) · 타임아웃·취소 · 실패한 호출의 라우터 좌석 · 러너가
  삼킨 예외 · 러너 WARNING). 이어 쓰기(이력).
- `<out>.run.json` — 실행 식별(실행 id · 평가셋 sha256 · git HEAD·src 수정 여부 · UTC 시각 · 설정과
  그 지문 · 선언 모델 핀 · 관측 모델 · 공급/미공급 · 결말·원인별 건수 · 종류별 발화 저자 분포 ·
  첫 프롬프트 지문과 유효 표본 상한 · 관측 싱크 구성·표면·flush 결과). 시작 시 `running`, 사례마다
  원자적 교체(짧은 재시도 — 중간 쓰기 실패는 경고만 하고 수집은 계속), 끝에 최종 상태.

`--resume` 규칙
---------------
응답 파일이 있으면 `run.json`도 있어야 하고, 마지막 실행의 **평가셋 지문·설정 지문·git HEAD**가
이번과 같아야 한다 — 하나라도 다르면 거부(exit 1). 다른 설정·다른 코드의 응답이 한 파일에 섞이지
않게 하기 위해서다(새로 시작하려면 다른 `--out`).

종료 코드 — 이번 실행이 아니라 **응답 파일 전체 상태**로 판정한다
--------------------------------------------------------------
- 0 — 완결(평가 사례 전부 응답) ∧ 라이브 비율 ≥ `--min-live-rate`(기본 0.5 — 제안값, Kiki 확인 전)
- 1 — 측정 실패: 준비 실패(레지스트리·평가셋·기존 산출물 충돌·손상·`run.json` 없음·지문/HEAD
  불일치·좌석 조립·최종 `run.json` 쓰기 실패) 또는 공허(파일 전체 라이브 0건)
- 2 — 인자 오류(argparse)
- 3 — 미완결 + 이번 실행에 실패가 있다 → 원인을 보고 `--resume`
- 4 — 완결이지만 라이브 비율 < `--min-live-rate` → 리포트는 낼 수 있으나 라이브 후보로 읽기엔 LLM
  발화 비중이 낮다
- 5 — 미완결 + 이번 실행 실패 0(`--limit`로 멈춤) → 남은 사례 수를 출력, `--resume`으로 이어서

프라이버시·비용·타임아웃
------------------------
평가 사례는 합성(학생 데이터 0)이지만 응답 원문은 `<out>`에만 둔다 — 진행 출력·stderr·실패 파일·
`run.json`에는 싣지 않는다(러너 WARNING은 러너의 프라이버시 계약상 발화 원문을 담지 않는다). 관측
표면은 `probe`(학생 대면 비용 표본과 분리). 모든 외부 호출에 시간 상한: provider 단일 호출(설정) ·
러너 한 턴(`--timeout`, 기본 = 서빙 설정) · 바깥 방어선(한 턴 + 프로즈 예산 + 10초) · git 조회 5초 ·
관측 flush 30초(데몬 스레드).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

from whymath_backend.config import Settings, get_settings
from whymath_backend.harness.ai_quality_candidates import (
    CANDIDATE_EOS,
    CandidateError,
    build_eos_candidate,
    dump_responses,
    parse_responses,
)
from whymath_backend.harness.ai_quality_eval_set import (
    KIND_HINT,
    EvalCase,
    EvalSet,
    EvalSetError,
    load_eval_set,
)
from whymath_backend.harness.ai_quality_judges import TutorResponse
from whymath_backend.harness.ai_quality_live_seat import (
    build_live_provider,
    build_live_trace,
    declared_model_pins,
    trace_configured,
)
from whymath_backend.harness.ai_quality_registry import (
    Registry,
    RegistryError,
    default_repo_root,
    load_registry,
)
from whymath_backend.harness.wh1_loop import EndTurnType
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import PRIMARY_ADOPTED
from whymath_backend.harness.wh1_shadow import record_logger as _observation_logger
from whymath_backend.harness.wh1_tutor_context import (
    ProblemBrief,
    TutorContentSummary,
    build_tutor_content_summary,
)
from whymath_backend.harness.wh1_tutor_output import (
    TutorOutputReceipt,
    TutorTurnOutput,
    build_tutor_output,
    check_deliverable,
)
from whymath_backend.l1.problem_bank.populate import (
    discover_problem_corpora,
    load_problem_bank_records,
)
from whymath_backend.l3.interfaces import (
    CacheBackend,
    InMemoryCache,
    LLMProvider,
    NamedEventSink,
    TraceSink,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.hint_deferral import decide_hint_level
from whymath_backend.l4.misconception import CATALOG, diagnose, reject_refuted
from whymath_backend.l4.misconception.distractor_link import distractor_link_matches
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis, curate
from whymath_backend.l4.misconception.match_gate import (
    apply_match_quality_gate,
    is_verdict_withheld,
)
from whymath_backend.l4.misconception.models import MisconceptionMatch

__all__ = [
    "DEFAULT_MIN_LIVE_RATE",
    "DEGRADED_ORIGIN",
    "EXIT_INCOMPLETE_FAILED",
    "EXIT_INCOMPLETE_LIMIT",
    "EXIT_LOW_LIVE",
    "EXIT_MEASUREMENT",
    "EXIT_OK",
    "FAILURE_SCHEMA",
    "FALLBACK_ORIGIN",
    "HARNESS_ORIGIN",
    "LIVE_ORIGIN",
    "RUN_SCHEMA",
    "UNCLASSIFIED_ORIGIN",
    "CaseLedger",
    "LiveDeps",
    "LiveTurnInputs",
    "RecordingProvider",
    "RecordingTrace",
    "coach_hypotheses",
    "default_deps",
    "exit_code_for",
    "live_turn_inputs",
    "main",
    "output_paths",
]

LIVE_ORIGIN: Final = "wh1-live"
HARNESS_ORIGIN: Final = "wh1-live:harness"
DEGRADED_ORIGIN: Final = "wh1-live:degraded"
FALLBACK_ORIGIN: Final = "wh1-live:fallback"
UNCLASSIFIED_ORIGIN: Final = "wh1-live:unclassified"
FAILURE_SCHEMA: Final = "ai-quality-live-failure/v1"
RUN_SCHEMA: Final = "ai-quality-live-run/v2"

EXIT_OK: Final = 0
EXIT_MEASUREMENT: Final = 1
EXIT_INCOMPLETE_FAILED: Final = 3
EXIT_LOW_LIVE: Final = 4
EXIT_INCOMPLETE_LIMIT: Final = 5
DEFAULT_MIN_LIVE_RATE: Final = 0.5

_EXCERPT_CHARS: Final = 300
_OUTER_GRACE_SECONDS: Final = 10.0
_GIT_TIMEOUT_SECONDS: Final = 5.0
_FLUSH_TIMEOUT_SECONDS: Final = 30.0
_CHAIN_LIMIT: Final = 5
_WRITE_RETRY_DELAYS: Final = (0.1, 0.3, 0.6)
"""`run.json` 원자적 교체 재시도 간격 — Windows에서 다른 프로세스가 파일을 잠깐 쥐면
`os.replace`가 PermissionError를 낸다."""

# 코치 텍스트 채널 상수(`api/coach.py` `_DEFAULT_TOP_K`·`_FANOUT`)와 같은 값.
_TEXT_TOP_K: Final = 3
_TEXT_FANOUT: Final = len(CATALOG)

_DEGRADED_OUTCOMES: Final = frozenset({"fallback_llm_degraded", "fallback_mode_guard"})
_ABORTED_OUTCOMES: Final = frozenset({"fallback_timeout", "fallback_exception"})
_MODE_GUARD_STRATEGY: Final = "socratic_requestion"
_STRATEGY_TO_ACTION: Final[Mapping[str, EndTurnType]] = {
    "guided_question": "질문",
    "guided_hint": "힌트",
    "diagnostic_probe": "출제",
    "encouragement": "격려",
}
"""`build_tutor_output`의 행위 유형 → 전략 매핑의 역(왕복 일치는 테스트가 빌더와 대조해 동결)."""

_HARNESS_LOGGER: Final = "whymath.harness"
_RUNNER_LOGGER: Final = "whymath.harness.wh1_primary"
_POLICY_LOGGER: Final = "whymath.harness.wh1_llm_policy"
_POLICY_PIPELINE_FAILURE: Final = "LLMTutorPolicy provider 호출 실패"
"""정책이 좌석(`Wh1LlmSeam` → 파이프라인) 예외를 강등으로 흡수할 때 남기는 WARNING 머리말."""
_TRACE_LOGGER: Final = "whymath.l3.trace"

_TRACE_FIELDS: Final = (
    "cost_tier",
    "local_family",
    "local_model",
    "served_model",
    "cloud_seat",
    "content_source",
    "cache_hit",
    "local_degraded",
    "call_site",
)
"""관측 트레이스에서 사례 회계로 옮기는 필드 — 라우팅·모델 식별뿐(텍스트 없음)."""

_MODEL_KEY: Final = ("cost_tier", "local_family", "local_model", "served_model", "cloud_seat")

_SECRET_LIKE: Final = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|pk-[A-Za-z0-9_\-]{6,}|Bearer\s+\S+)")

_SUPPLIED: Final = ("concept", "problem_brief", "initial_hypotheses", "hint_level")
_UNSUPPLIED: Final = (
    "skills",
    "pedagogy_pack",
    "tutor_context_manifest",
    "session(select_probe 후보)",
    "session_recall",
    "warmstart_outside_mids",
    "theta",
    "grade",
    "mastery",
)


# ──────────────────────────────────────────────────────────────────────────
# 사례 회계 — 래퍼·싱크·로그 캡처가 이번 사례 몫을 여기 모은다
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class CaseLedger:
    """사례 1건 동안 모인 것 — provider 예외·호출 지문·트레이스·관측 레코드·러너 WARNING."""

    faults: list[dict[str, object]] = field(default_factory=list)
    prompt_fingerprints: list[str] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)
    warnings: list[dict[str, object]] = field(default_factory=list)


class _Scope:
    """현재 사례의 회계 좌석 — 사례는 순차로 돌므로 한 칸이면 충분하다."""

    def __init__(self) -> None:
        self.ledger = CaseLedger()


def _plain(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _clip(text: str) -> str:
    squashed = " ".join(text.split())
    masked = _SECRET_LIKE.sub("***", squashed)
    return masked if len(masked) <= _EXCERPT_CHARS else masked[: _EXCERPT_CHARS - 1] + "…"


def _timeout_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [TimeoutError]
    try:
        import httpx

        types.append(httpx.TimeoutException)
    except ImportError:  # pragma: no cover — 환경 의존(httpx 미설치)
        pass
    return tuple(types)


def _chain(exc: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(out) < _CHAIN_LIMIT:
        out.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return out


def _status_of(exc: BaseException) -> int | None:
    """HTTP 상태코드 — 속성만 읽는다(`status_code` · `response.status_code` — 메시지 파싱 0)."""
    candidates: list[object] = [getattr(exc, "status_code", None)]
    response = getattr(exc, "response", None)
    if response is not None:
        candidates.append(getattr(response, "status_code", None))
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _body_of(exc: BaseException) -> str | None:
    """오류 응답 본문 — SDK `body` · httpx `response.text` · ollama `error` 순(없으면 None)."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict | list):
        return json.dumps(body, ensure_ascii=False)
    if isinstance(body, str) and body.strip():
        return body
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            text = getattr(response, "text", None)
        except Exception:  # noqa: BLE001 — 본문 미적재(httpx.ResponseNotRead 등)는 '본문 없음'이다.
            text = None
        if isinstance(text, str) and text.strip():
            return text
    error = getattr(exc, "error", None)
    if isinstance(error, str) and error.strip():
        return error
    return None


def describe_fault(
    exc: BaseException, decision: RoutingDecision | None, *, cancelled: bool = False
) -> dict[str, object]:
    """예외 1건 → 실패 파일 항목. 추출 자체가 실패해도 타입명은 남긴다(침묵 실패 금지)."""
    fault: dict[str, object] = {
        "exc_type": type(exc).__name__,
        "cancelled": cancelled,
        "seat": {
            "cost_tier": _plain(getattr(decision, "cost_tier", None)),
            "local_family": _plain(getattr(decision, "local_family", None)),
            "local_model": _plain(getattr(decision, "local_model", None)),
        },
    }
    try:
        chain = _chain(exc)
        timeouts = _timeout_types()
        status = next((s for s in map(_status_of, chain) if s is not None), None)
        body = next((b for b in map(_body_of, chain) if b is not None), None)
        fault.update(
            {
                "chain": [type(e).__name__ for e in chain],
                "http_status": status,
                "body_excerpt": _clip(body) if body is not None else None,
                "message_excerpt": _clip(str(exc)) if str(exc) else None,
                "timeout": cancelled or any(isinstance(e, timeouts) for e in chain),
            }
        )
    except Exception as extract_exc:  # noqa: BLE001 — 원인 추출 실패도 기록은 남긴다.
        fault["extraction_error"] = type(extract_exc).__name__
        fault["timeout"] = cancelled
    return fault


def _fingerprint(system: str, prompt: str) -> str:
    return hashlib.sha256(f"{system}\x1f{prompt}".encode()).hexdigest()


class RecordingProvider:
    """안쪽 provider로 **그대로 전달**하며 이번 사례의 호출 지문·예외를 기록한다.

    이 래퍼는 호출을 만들지 않는다 — `l3.pipeline`이 라우터 결정(`decision`)을 실어 부른 것을
    받은 그대로 넘긴다. 선택 인자는 받은 것만 넘긴다. 좌석 표면(`cloud_seat` 등)은 안쪽 것을
    그대로 보인다(`__getattr__`) — 파이프라인의 원가 좌석 판정이 래퍼 때문에 바뀌지 않게.
    프롬프트는 **지문(sha256)만** 남긴다(원문 0).
    """

    def __init__(self, inner: LLMProvider, scope: _Scope) -> None:
        self._inner = inner
        self._scope = scope

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        optional: dict[str, Any] = {
            key: value
            for key, value in (
                ("images", images),
                ("temperature", temperature),
                ("top_p", top_p),
                ("json_schema", json_schema),
                ("seed", seed),
            )
            if value is not None
        }
        self._scope.ledger.prompt_fingerprints.append(_fingerprint(system, prompt))
        try:
            return await self._inner.generate(prompt, system, decision, **optional)
        except asyncio.CancelledError as exc:
            # 러너 타임아웃이 비행 중 호출을 끊은 경우 — '타임아웃 여부'의 직접 증거다.
            self._scope.ledger.faults.append(describe_fault(exc, decision, cancelled=True))
            raise
        except Exception as exc:
            self._scope.ledger.faults.append(describe_fault(exc, decision))
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RecordingTrace:
    """안쪽 관측 싱크로 그대로 넘기며, 라우팅·모델 식별 필드만 이번 사례 회계에 복사한다."""

    def __init__(self, inner: TraceSink, scope: _Scope) -> None:
        self._inner = inner
        self._scope = scope

    def record(self, fields: dict[str, object]) -> None:
        self._scope.ledger.calls.append({key: fields.get(key) for key in _TRACE_FIELDS})
        self._inner.record(fields)

    def record_event(self, name: str, fields: dict[str, object]) -> None:
        if isinstance(self._inner, NamedEventSink):
            self._inner.record_event(name, fields)

    def flush(self) -> None:
        flush = getattr(self._inner, "flush", None)
        if callable(flush):
            flush()


class _ObservationHandler(logging.Handler):
    """러너 관측 레코드(JSON 한 줄)를 붙잡는다 — 비식별 필드뿐이다(`extra="forbid"` 모델)."""

    def __init__(self, sink: list[dict[str, object]]) -> None:
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict):
            self._sink.append(payload)


class _WarningHandler(logging.Handler):
    """하네스·관측 WARNING을 붙잡는다 — 로거 이름·메시지 일부·`exc_info`의 예외 서술.

    러너·정책·싱크의 WARNING은 각자의 프라이버시 계약상 예외 타입명·사유 코드만 싣는다(발화 원문
    없음). 메시지는 그래도 300자로 자르고 키 모양 문자열을 가린다.
    """

    def __init__(self, sink: list[dict[str, object]]) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, object] = {
            "logger": record.name,
            "template": str(record.msg)[:80],
            "message": _clip(record.getMessage()),
            "arg_types": (
                [a for a in (record.args or ()) if isinstance(a, str)][:3]
                if isinstance(record.args, tuple)
                else []
            ),
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = describe_fault(record.exc_info[1], None)
        self._sink.append(entry)


@contextmanager
def _capture_logs(ledger: CaseLedger) -> Iterator[None]:
    """관측 로거(INFO)와 하네스 로거(WARNING)에 붙잡기 핸들러를 잠시 단다 — 끝나면 원복한다."""
    observation = _ObservationHandler(ledger.observations)
    warning = _WarningHandler(ledger.warnings)
    harness_logger = logging.getLogger(_HARNESS_LOGGER)
    previous = _observation_logger.level
    if not _observation_logger.isEnabledFor(logging.INFO):
        _observation_logger.setLevel(logging.INFO)
    _observation_logger.addHandler(observation)
    harness_logger.addHandler(warning)
    try:
        yield
    finally:
        harness_logger.removeHandler(warning)
        _observation_logger.removeHandler(observation)
        _observation_logger.setLevel(previous)


# ──────────────────────────────────────────────────────────────────────────
# 사례 → 러너 입력(코치 요청 처리 재현)
# ──────────────────────────────────────────────────────────────────────────
def coach_hypotheses(
    student_text: str,
    *,
    distractor_map: Sequence[Mapping[str, Any]],
    selected_choice_index: int | None,
    settings: Settings,
) -> tuple[MisconceptionHypothesis, ...]:
    """코치의 초기 활성 가설을 처음 보는 학생 기준으로 재현한다(모듈 docstring '초기 가설')."""
    text_matches = diagnose(student_text, top_k=_TEXT_FANOUT)[:_TEXT_TOP_K]
    text_matches = reject_refuted(text_matches, student_text)
    gate = apply_match_quality_gate(text_matches, ocr_confidence=None)
    persisted: list[MisconceptionMatch] = (
        []
        if is_verdict_withheld(
            low_quality=gate.low_quality, attribution_unclear=gate.attribution_unclear
        )
        else list(gate.matches)
    )
    distractor: list[MisconceptionMatch] = []
    if selected_choice_index is not None and settings.l4_distractor_link_enabled:
        distractor = distractor_link_matches(list(distractor_map), selected_choice_index)
    known = {m.misconception.id for m in persisted}
    merged = persisted + [m for m in distractor if m.misconception.id not in known]
    return tuple(curate([], merged))


@dataclass(frozen=True)
class LiveTurnInputs:
    """러너 한 턴 입력 — 코치가 같은 요청에서 만드는 값(모듈 docstring '사례 → 러너 입력')."""

    student_input: str
    student_solution: str
    solution_steps: tuple[str, ...]
    selected_choice_index: int | None
    active_hypotheses: tuple[MisconceptionHypothesis, ...]
    hint_level: int
    turn_index: int
    problem_id: str
    tutor_content: TutorContentSummary


def _problem_brief(problem: Any) -> ProblemBrief:
    """검증된 `Problem` → 코치 `_problem_brief_for`와 같은 변환."""
    question_format = getattr(problem, "question_format", None)
    bloom_level = getattr(problem, "bloom_level", None)
    condition_count = getattr(problem, "condition_count", None)
    return ProblemBrief(
        question_format=(str(_plain(question_format)) if question_format is not None else None),
        bloom_level=str(_plain(bloom_level)) if bloom_level is not None else None,
        has_visual=bool(getattr(problem, "has_visual", False)),
        condition_count=min(int(condition_count), 20) if condition_count is not None else None,
    )


def load_problem_briefs(
    eval_set: EvalSet, root: Path | None = None
) -> tuple[dict[str, ProblemBrief], dict[str, str]]:
    """평가 사례 문항의 `ProblemBrief` — 적재기(`load_problem_bank_records`)로 검증한 행에서.

    반환: (problem_id → 요약, 코퍼스 파일 → 적재 실패 예외 타입명). 실패한 파일의 문항은 요약 없이
    (문제 슬롯 미공급) 진행하고 그 사실을 `run.json`에 남긴다.
    """
    base = root or default_repo_root()
    wanted = set(eval_set.materials)
    briefs: dict[str, ProblemBrief] = {}
    errors: dict[str, str] = {}
    # 코퍼스 발견은 DB 적재(`populate --all`)와 같은 함수 — 글롭을 따로 두지 않는다.
    for path in discover_problem_corpora(base):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors[str(path)] = type(exc).__name__
            continue
        if not any(pid in text for pid in wanted - set(briefs)):
            continue
        try:
            records = load_problem_bank_records(path)
        except Exception as exc:  # noqa: BLE001 — 한 파일의 위생 실패가 수집 전체를 막지 않는다.
            errors[str(path)] = type(exc).__name__
            continue
        for record in records:
            pid = str(record.problem.problem_id)
            if pid in wanted and pid not in briefs:
                briefs[pid] = _problem_brief(record.problem)
    return briefs, errors


def live_turn_inputs(
    case: EvalCase,
    eval_set: EvalSet,
    registry: Registry,
    *,
    settings: Settings,
    briefs: Mapping[str, ProblemBrief] | None = None,
) -> LiveTurnInputs:
    material = eval_set.materials[case.problem_id]
    content = build_tutor_content_summary(
        concept_code=case.concept_id,
        concept_name=registry.concepts[case.concept_id].name_ko,
        skills=(),
        skill_total=0,
        problem=(briefs or {}).get(case.problem_id),
        pack=None,
    )
    if case.kind == KIND_HINT:
        assert case.signals is not None
        student_input = case.signals.student_input
        turn_count = case.signals.turn_count
        prev_hint_level = case.signals.prev_hint_level
        selected: int | None = None
        turn_index = (
            turn_count + 1
        )  # append_turns: total_turns // 2 + 1, total_turns = 2·turn_count
    else:
        assert case.selected_choice_index is not None
        student_input = material.choices[case.selected_choice_index]
        turn_count, prev_hint_level = 0, None  # create_session: 새 대화·처음 보는 학생
        selected = case.selected_choice_index
        turn_index = 1
    return LiveTurnInputs(
        student_input=student_input,
        # 코치: `student_solution or student_input` — 앱은 student_solution을 보내지 않는다.
        student_solution=student_input,
        # 코치: `solution_steps or []` — 대화 모드(`ChatController.send`)는 단계를 보내지 않는다.
        solution_steps=(),
        selected_choice_index=selected,
        active_hypotheses=coach_hypotheses(
            student_input,
            distractor_map=material.distractor_map,
            selected_choice_index=selected,
            settings=settings,
        ),
        hint_level=decide_hint_level(
            student_input=student_input, turn_count=turn_count, prev_hint_level=prev_hint_level
        ),
        turn_index=turn_index,
        problem_id=str(material.problem_uuid),
        tutor_content=content,
    )


# ──────────────────────────────────────────────────────────────────────────
# 결말 분류
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CaseResult:
    case_id: str
    kind: str
    category: str
    """live / harness / degraded / fallback / unclassified / failed."""
    response: TutorResponse | None
    failure: dict[str, object] | None
    primary_outcome: str | None
    elapsed_ms: int
    calls: tuple[dict[str, object], ...]
    provider_calls: int
    first_prompt: str | None
    rebuild_rejected: bool = False
    cause: str | None = None
    """degraded 원인(output_schema/mode_guard/unknown) 또는 실패 종류."""


def _primary_observation(observations: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    for record in reversed(observations):
        if record.get("primary") is True:
            return record
    return {}


def _swallowed(ledger: CaseLedger, logger_name: str) -> list[dict[str, object]]:
    """그 로거의 WARNING에 실린 `exc_info` 예외 서술 — 러너가 삼킨 예외의 원인."""
    found: list[dict[str, object]] = []
    for warning in ledger.warnings:
        exception = warning.get("exception")
        if warning.get("logger") == logger_name and isinstance(exception, dict):
            found.append(exception)
    return found


def _pipeline_failure(ledger: CaseLedger) -> dict[str, object] | None:
    """정책이 provider 밖 예외(좌석·파이프라인·라우터·캐시)를 강등으로 흡수한 WARNING."""
    for w in ledger.warnings:
        template = w.get("template")
        if (
            w.get("logger") == _POLICY_LOGGER
            and isinstance(template, str)
            and template.startswith(_POLICY_PIPELINE_FAILURE)
        ):
            return w
    return None


def _rebuild(
    case: EvalCase, inputs: LiveTurnInputs, served: TutorTurnOutput
) -> tuple[dict[str, Any], str | None]:
    """사례 판정 기준으로 같은 빌더에 다시 조립 — 거부되면 러너가 서빙한 구조체 + 주석."""
    rebuilt = build_tutor_output(
        explanation=served.explanation,
        explanation_source=served.explanation_source,
        action_type=_STRATEGY_TO_ACTION.get(served.response_strategy),
        mode_guard_replaced=served.response_strategy == _MODE_GUARD_STRATEGY,
        verify_verdict=case.verdict,
        hypotheses=inputs.active_hypotheses,
        concept_id=case.concept_id,
        known_concept_ids=frozenset({case.concept_id}),
        hint_level=inputs.hint_level,
    )
    if isinstance(rebuilt, str):
        note = (
            f"사례 판정 기준 재조립을 P3-09가 거부({rebuilt}) — 러너가 서빙한 구조체(하네스 판정 "
            "기준)를 그대로 싣는다"
        )
        return served.model_dump(mode="json"), note
    return rebuilt.model_dump(mode="json"), None


def classify_case(
    case: EvalCase,
    inputs: LiveTurnInputs | None,
    *,
    utterance: str | None,
    receipt: TutorOutputReceipt,
    ledger: CaseLedger,
    eos: TutorResponse,
    outer_error: tuple[str, str | None] | None,
    elapsed_ms: int,
    run_id: str = "",
) -> CaseResult:
    """러너 결과·회계 → 결말 1건(모듈 docstring '사례 결말'). 실패는 응답을 만들지 않는다."""
    observation = _primary_observation(ledger.observations)
    raw_outcome = observation.get("primary_outcome")
    outcome = raw_outcome if isinstance(raw_outcome, str) else None
    calls = tuple(ledger.calls)
    first_prompt = ledger.prompt_fingerprints[0] if ledger.prompt_fingerprints else None

    def _result(category: str, response: TutorResponse | None, **extra: Any) -> CaseResult:
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            category=category,
            response=response,
            failure=extra.pop("failure", None),
            primary_outcome=outcome,
            elapsed_ms=elapsed_ms,
            calls=calls,
            provider_calls=len(ledger.prompt_fingerprints),
            first_prompt=first_prompt,
            **extra,
        )

    def _failed(
        kind: str,
        *,
        exc_type: str | None = None,
        timeout: bool = False,
        swallowed: Sequence[dict[str, object]] = (),
    ) -> CaseResult:
        if exc_type is None and swallowed:
            first = swallowed[0].get("exc_type")
            exc_type = first if isinstance(first, str) else None
        if exc_type is None and ledger.faults:
            first = ledger.faults[0].get("exc_type")
            exc_type = first if isinstance(first, str) else None
        record: dict[str, object] = {
            "schema": FAILURE_SCHEMA,
            "run_id": run_id,
            "case_id": case.case_id,
            "at": _utc_now(),
            "kind": kind,
            "exc_type": exc_type,
            "timeout": timeout or any(f.get("timeout") is True for f in ledger.faults),
            "primary_outcome": outcome,
            "faults": list(ledger.faults),
            "swallowed": list(swallowed),
            "warnings": list(ledger.warnings),
            "provider_calls": len(ledger.prompt_fingerprints),
            "llm_calls_recorded": len(ledger.calls),
            "elapsed_ms": elapsed_ms,
        }
        return _result("failed", None, failure=record, cause=kind)

    def _fallback(reason: str) -> CaseResult:
        note = f"primary 폴백({reason}) — 서빙과 같은 결정론 폴백: {CANDIDATE_EOS} 응답을 싣는다"
        if eos.note:
            note = f"{note} · 결정론 주석: {eos.note}"
        return _result("fallback", replace(eos, origin=FALLBACK_ORIGIN, note=note))

    # 순서: 바깥 방어선 → 러너 중단(삼킨 예외 포함) → provider 예외 → 파이프라인 예외 흡수 → 폴백
    # → 응답. provider·파이프라인 예외는 정책이 강등으로 흡수해 턴은 끝났어도 인프라 실패다.
    if outer_error is not None:
        kind, exc_type = outer_error
        return _failed(kind, exc_type=exc_type, timeout=kind == "outer_timeout")
    if outcome in _ABORTED_OUTCOMES:
        return _failed(
            "runner_timeout" if outcome == "fallback_timeout" else "runner_exception",
            timeout=outcome == "fallback_timeout",
            swallowed=_swallowed(ledger, _RUNNER_LOGGER),
        )
    if ledger.faults:
        return _failed("provider_error")
    pipeline = _pipeline_failure(ledger)
    if pipeline is not None and outcome == "fallback_llm_degraded":
        arg_types = pipeline.get("arg_types")
        exc_type = arg_types[0] if isinstance(arg_types, list) and arg_types else None
        return _failed("pipeline_error", exc_type=exc_type if isinstance(exc_type, str) else None)
    if utterance is None or inputs is None:
        return _fallback(outcome or "결말 미상 — 관측 레코드 없음")
    rejection = check_deliverable(
        receipt.output, utterance=utterance, known_concept_ids=frozenset({case.concept_id})
    )
    if rejection is not None or receipt.output is None:
        return _fallback(f"승격 직전 재검증 거부({rejection})")
    served = receipt.output
    tutor_output, rebuild_note = _rebuild(case, inputs, served)
    cause: str | None = None
    if outcome == PRIMARY_ADOPTED and served.explanation_source == "llm":
        category, origin, note = "live", LIVE_ORIGIN, rebuild_note
    elif outcome == PRIMARY_ADOPTED:
        category, origin = "harness", HARNESS_ORIGIN
        note = (
            "채택됐지만 본문이 하네스 파생 템플릿이다(LLM은 행위만 골랐다) — 라이브로 세지 않는다"
        )
    elif outcome in _DEGRADED_OUTCOMES:
        category, origin = "degraded", DEGRADED_ORIGIN
        rejections = observation.get("llm_output_rejections")
        if outcome == "fallback_mode_guard":
            cause = "mode_guard"
        elif isinstance(rejections, int) and rejections > 0:
            cause = "output_schema"
        else:
            cause = "unknown"
        note = f"하네스 결정론 발화({outcome} · 원인 {cause}) — LLM 발화가 아니다"
    else:
        category, origin = "unclassified", UNCLASSIFIED_ORIGIN
        note = f"결말 미분류(primary_outcome={outcome!r}) — 라이브로 세지 않는다"
    if rebuild_note and category != "live":
        note = f"{note} · {rebuild_note}"
    response = TutorResponse(
        case_id=case.case_id, tutor_output=tutor_output, origin=origin, note=note
    )
    return _result(category, response, rebuild_rejected=rebuild_note is not None, cause=cause)


# ──────────────────────────────────────────────────────────────────────────
# 의존 조립
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiveDeps:
    """한 실행의 L3 의존 — provider·관측·사례별 캐시 공장 + 선언 모델 핀(실행 식별용)."""

    provider: LLMProvider
    trace: TraceSink
    declared_models: Mapping[str, object]
    trace_configured: bool | None
    cache_factory: Callable[[], CacheBackend] = InMemoryCache


def default_deps(settings: Settings) -> LiveDeps:
    """서빙과 같은 팩토리(`ai_quality_live_seat`) + 사례마다 새 인메모리 캐시."""
    trace = build_live_trace()
    return LiveDeps(
        provider=build_live_provider(settings),
        trace=trace,
        declared_models=declared_model_pins(settings),
        trace_configured=trace_configured(trace),
    )


# ──────────────────────────────────────────────────────────────────────────
# 산출물 입출력
# ──────────────────────────────────────────────────────────────────────────
class _SetupError(RuntimeError):
    """실행 준비 실패 — 측정 실패(exit 1)로 올린다."""


def output_paths(out: Path) -> tuple[Path, Path]:
    """(실패 파일, 실행 식별 파일) — 응답 파일 옆에 둔다."""
    return out.with_name(out.name + ".failures.jsonl"), out.with_name(out.name + ".run.json")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _append_line(path: Path, line: str) -> None:
    """한 줄을 쓰고 즉시 flush·fsync — 중간에 멈춰도 쓴 줄은 남는다."""
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    """임시 파일 + `os.replace` — 잠금 경합(PermissionError 등)은 짧게 재시도, 끝내 실패면 올린다.

    Windows에서 다른 프로세스가 파일을 잠깐 쥐면 `os.replace`가 PermissionError를 낸다.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for delay in (*_WRITE_RETRY_DELAYS, None):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if delay is None:
                raise
            time.sleep(delay)


def _config_fingerprint(config: Mapping[str, object]) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class _Existing:
    done: dict[str, TutorResponse]
    prior_runs: list[object]
    prompts: dict[str, str]


def _load_existing(
    out: Path,
    run_path: Path,
    eval_set: EvalSet,
    *,
    config_fingerprint: str,
    git_head: str | None,
) -> _Existing:
    """`--resume`: 이미 쓴 응답·이전 실행 기록. 손상·식별 불일치는 거부(증거를 덮지 않는다)."""
    done: dict[str, TutorResponse] = {}
    if out.exists():
        text = out.read_text(encoding="utf-8")
        if text.strip():
            try:
                done = parse_responses(text, source=str(out))
            except CandidateError as exc:
                raise _SetupError(
                    f"기존 응답 파일이 손상됐다({exc}) — 마지막 줄이 잘렸다면 그 줄만 지우고 다시 "
                    "--resume"
                ) from exc
    unknown = sorted(set(done) - {c.case_id for c in eval_set.cases})
    if unknown:
        raise _SetupError(f"기존 응답에 이 평가셋에 없는 사례 {len(unknown)}건: {unknown[:3]}")
    if not run_path.exists():
        if out.exists():
            raise _SetupError(
                f"{run_path} 가 없다 — 실행 식별 없이 응답 파일에 이어 붙이지 않는다(새 --out 으로)"
            )
        return _Existing(done={}, prior_runs=[], prompts={})
    try:
        previous = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _SetupError(f"{run_path}: 읽지 못했다({type(exc).__name__})") from exc
    if not isinstance(previous, dict):
        raise _SetupError(f"{run_path}: 객체가 아니다")
    sha = (previous.get("eval_set") or {}).get("sha256")
    if sha != eval_set.sha256:
        raise _SetupError(
            f"평가셋 지문 불일치 — 이전 실행 {str(sha)[:12]} ≠ 이번 {eval_set.sha256[:12]}"
            "(다른 평가셋의 응답과 섞이지 않게 새 --out 으로 시작하라)"
        )
    prior = previous.get("runs")
    runs = list(prior) if isinstance(prior, list) else []
    last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    if last.get("config_fingerprint") != config_fingerprint:
        raise _SetupError(
            "설정 지문 불일치 — 모델 매트릭스·클라우드 좌석/핀·프로즈·타임아웃·진단 채널 설정이 "
            "이전 실행과 다르다(같은 파일에 다른 설정의 응답을 섞지 않는다 — 새 --out 으로)"
        )
    previous_head = (
        (last.get("git") or {}).get("head") if isinstance(last.get("git"), dict) else None
    )
    if previous_head != git_head:
        raise _SetupError(
            f"git HEAD 불일치 — 이전 실행 {str(previous_head)[:12]} ≠ 이번 {str(git_head)[:12]}"
            "(다른 코드의 응답을 섞지 않는다 — 새 --out 으로)"
        )
    prompts: dict[str, str] = {}
    for run in runs:
        if isinstance(run, dict) and isinstance(run.get("first_prompts"), dict):
            prompts.update({str(k): str(v) for k, v in run["first_prompts"].items()})
    return _Existing(done=done, prior_runs=runs, prompts=prompts)


def _git_identity(root: Path) -> dict[str, object]:
    def _git(*args: str) -> str | None:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else None

    try:
        head = _git("rev-parse", "HEAD")
        # 산출물을 저장소 안(`data/runs/...`)에 쓰면 작업 트리는 늘 dirty다 — 코드(src) 수정만 본다.
        status = _git("status", "--porcelain", "--untracked-files=no", "--", "src")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"head": None, "dirty_src": None, "error": type(exc).__name__}
    return {"head": head, "dirty_src": None if status is None else bool(status)}


class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def _flush_trace(trace: TraceSink, configured: bool | None) -> str:
    """관측 flush — 미구성이면 건너뛴 사실을, 아니면 결과(ok·경고 수·타임아웃·예외)를 적는다.

    `LangfuseSink.flush`는 실패를 삼키고 WARNING만 남기므로(never-break) 그 경고를 세어 'ok'로
    위장되지 않게 한다. 데몬 스레드라 네트워크가 멈춰도 프로세스 종료를 막지 않는다.
    """
    if configured is False:
        return "skipped_not_configured"
    flush = getattr(trace, "flush", None)
    if not callable(flush):
        return "not_supported"
    box: dict[str, str] = {}
    counter = _CountingHandler()
    trace_logger = logging.getLogger(_TRACE_LOGGER)
    trace_logger.addHandler(counter)

    def _run() -> None:
        try:
            flush()
            box["result"] = "ok"
        except Exception as exc:  # noqa: BLE001 — flush 실패는 기록하고 계속(타입명 포함).
            box["result"] = f"error:{type(exc).__name__}"

    try:
        worker = threading.Thread(target=_run, name="aq-live-trace-flush", daemon=True)
        worker.start()
        worker.join(_FLUSH_TIMEOUT_SECONDS)
    finally:
        trace_logger.removeHandler(counter)
    if worker.is_alive():
        return "timeout"
    result = box.get("result", "error:unknown")
    if result == "ok" and counter.count:
        return f"warned:{counter.count}"
    return result


# ──────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _RunCounts:
    attempted: int = 0
    live: int = 0
    harness: int = 0
    degraded: int = 0
    fallback: int = 0
    unclassified: int = 0
    failed: int = 0
    skipped_resume: int = 0
    rebuild_rejected: int = 0
    provider_calls: int = 0
    trace_records: int = 0
    cache_hits: int = 0
    provider_faults: int = 0
    run_json_write_errors: int = 0
    degraded_causes: Counter[str] = field(default_factory=Counter)
    failure_kinds: Counter[str] = field(default_factory=Counter)
    primary_outcomes: Counter[str] = field(default_factory=Counter)
    explanation_sources: dict[str, Counter[str]] = field(default_factory=dict)
    models: Counter[tuple[object, ...]] = field(default_factory=Counter)

    def add(self, result: CaseResult) -> None:
        self.attempted += 1
        setattr(self, result.category, getattr(self, result.category) + 1)
        self.rebuild_rejected += int(result.rebuild_rejected)
        self.primary_outcomes[result.primary_outcome or "none"] += 1
        self.provider_calls += result.provider_calls
        if result.category == "degraded" and result.cause:
            self.degraded_causes[result.cause] += 1
        if result.failure is not None:
            self.failure_kinds[str(result.failure.get("kind"))] += 1
            faults = result.failure.get("faults")
            self.provider_faults += len(faults) if isinstance(faults, list) else 0
        if result.response is not None:
            source = result.response.tutor_output.get("explanation_source")
            bucket = self.explanation_sources.setdefault(result.kind, Counter())
            bucket[str(source)] += 1
        for call in result.calls:
            self.trace_records += 1
            if call.get("cache_hit") is True:
                self.cache_hits += 1
            self.models[tuple(call.get(key) for key in _MODEL_KEY)] += 1

    def to_json(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "live": self.live,
            "harness": self.harness,
            "degraded": self.degraded,
            "degraded_causes": dict(sorted(self.degraded_causes.items())),
            "fallback": self.fallback,
            "unclassified": self.unclassified,
            "failed": self.failed,
            "failure_kinds": dict(sorted(self.failure_kinds.items())),
            "skipped_resume": self.skipped_resume,
            "rebuild_rejected": self.rebuild_rejected,
            "provider_calls": self.provider_calls,
            "trace_records": self.trace_records,
            "cache_hits": self.cache_hits,
            "provider_faults": self.provider_faults,
            "run_json_write_errors": self.run_json_write_errors,
            "live_rate": (self.live / self.attempted) if self.attempted else None,
            "explanation_source_by_kind": {
                kind: dict(sorted(c.items()))
                for kind, c in sorted(self.explanation_sources.items())
            },
        }


def _distinct(prompts: Mapping[str, str], cases: Sequence[EvalCase]) -> dict[str, int]:
    by_kind: dict[str, set[str]] = {}
    for case in cases:
        fingerprint = prompts.get(case.case_id)
        if fingerprint is not None:
            by_kind.setdefault(case.kind, set()).add(fingerprint)
    total = set().union(*by_kind.values()) if by_kind else set()
    return {"total": len(total), **{kind: len(v) for kind, v in sorted(by_kind.items())}}


@dataclass
class _Run:
    """한 실행의 상태 — 사례마다 `run.json`을 다시 쓴다."""

    out: Path
    run_path: Path
    eval_set: EvalSet
    prior_runs: list[object]
    record: dict[str, object]
    responses: dict[str, str] = field(default_factory=dict)
    """case_id → origin(파일 전체 — 이전 실행분 포함)."""
    prompts: dict[str, str] = field(default_factory=dict)
    """case_id → 첫 정책 프롬프트 지문(파일 전체 — 이전 실행분 포함)."""
    counts: _RunCounts = field(default_factory=_RunCounts)
    run_prompts: dict[str, str] = field(default_factory=dict)

    def file_totals(self) -> dict[str, object]:
        n = len(self.eval_set.cases)
        origins = Counter(self.responses.values())
        live = origins.get(LIVE_ORIGIN, 0)
        answered = [c for c in self.eval_set.cases if c.case_id in self.responses]
        return {
            "cases": n,
            "responses": len(self.responses),
            "remaining": n - len(self.responses),
            "complete": len(self.responses) == n,
            "by_origin": dict(sorted(origins.items())),
            "live": live,
            "live_rate": live / n if n else None,
            "distinct_first_prompts": _distinct(self.prompts, answered),
            "effective_sample_upper_bound": _distinct(self.prompts, answered)["total"],
        }

    def payload(self) -> dict[str, object]:
        self.record["counts"] = self.counts.to_json()
        self.record["primary_outcomes"] = dict(sorted(self.counts.primary_outcomes.items()))
        self.record["observed_models"] = [
            {**dict(zip(_MODEL_KEY, key, strict=True)), "calls": n}
            for key, n in self.counts.models.most_common()
        ]
        self.record["first_prompts"] = dict(sorted(self.run_prompts.items()))
        self.record["distinct_first_prompts"] = _distinct(self.run_prompts, self.eval_set.cases)
        return {
            "schema": RUN_SCHEMA,
            "responses": str(self.out),
            "eval_set": {
                "source": self.eval_set.source,
                "sha256": self.eval_set.sha256,
                "cases": len(self.eval_set.cases),
            },
            "file_totals": self.file_totals(),
            "runs": [*self.prior_runs, self.record],
        }

    def write(self, *, final: bool = False) -> None:
        """중간 쓰기 실패는 경고만(수집 계속 — 응답 파일이 1차 증거다), 최종 쓰기 실패는 올린다."""
        try:
            _write_json_atomic(self.run_path, self.payload())
        except OSError as exc:
            if final:
                raise
            self.counts.run_json_write_errors += 1
            print(
                f"경고 — run.json 갱신 실패({type(exc).__name__}) · 수집은 계속한다",
                file=sys.stderr,
                flush=True,
            )


def exit_code_for(
    totals: Mapping[str, object], *, failed_this_run: int, min_live_rate: float
) -> int:
    """종료 코드 규약(모듈 docstring) — 응답 파일 전체 상태로 판정한다."""
    live = totals.get("live")
    if not isinstance(live, int) or live == 0:
        return EXIT_MEASUREMENT
    if totals.get("complete") is not True:
        return EXIT_INCOMPLETE_FAILED if failed_this_run > 0 else EXIT_INCOMPLETE_LIMIT
    rate = totals.get("live_rate")
    if not isinstance(rate, float | int) or rate < min_live_rate:
        return EXIT_LOW_LIVE
    return EXIT_OK


@dataclass(frozen=True)
class _Context:
    eval_set: EvalSet
    registry: Registry
    eos: Mapping[str, TutorResponse]
    briefs: Mapping[str, ProblemBrief]
    settings: Settings
    provider: LLMProvider
    trace: TraceSink
    cache_factory: Callable[[], CacheBackend]
    scope: _Scope
    turn_timeout: float
    outer_timeout: float
    run_id: str


async def _run_case(case: EvalCase, ctx: _Context) -> CaseResult:
    ledger = CaseLedger()
    ctx.scope.ledger = ledger
    receipt = TutorOutputReceipt()
    started = time.monotonic()
    utterance: str | None = None
    inputs: LiveTurnInputs | None = None
    outer_error: tuple[str, str | None] | None = None
    try:
        inputs = live_turn_inputs(
            case, ctx.eval_set, ctx.registry, settings=ctx.settings, briefs=ctx.briefs
        )
        with _capture_logs(ledger):
            utterance = await asyncio.wait_for(
                run_wh1_primary_turn(
                    student_solution=inputs.student_solution,
                    solution_steps=list(inputs.solution_steps),
                    active_hypotheses=list(inputs.active_hypotheses),
                    provider=ctx.provider,
                    # 사례마다 새 캐시 — 앞 사례 응답이 이 사례로 재생되지 않는다.
                    cache=ctx.cache_factory(),
                    trace=ctx.trace,
                    turn_index=inputs.turn_index,
                    timeout_seconds=ctx.turn_timeout,
                    problem_id=inputs.problem_id,
                    tutor_content=inputs.tutor_content,
                    hint_level=inputs.hint_level,
                    output_receipt=receipt,
                ),
                timeout=ctx.outer_timeout,
            )
    except TimeoutError:
        outer_error = ("outer_timeout", "TimeoutError")
    except Exception as exc:  # noqa: BLE001 — 한 사례의 예외가 나머지를 멈추지 않는다(타입명 기록).
        outer_error = ("collector_error", type(exc).__name__)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    return classify_case(
        case,
        inputs,
        utterance=utterance,
        receipt=receipt,
        ledger=ledger,
        eos=ctx.eos[case.case_id],
        outer_error=outer_error,
        elapsed_ms=elapsed_ms,
        run_id=ctx.run_id,
    )


def _progress(index: int, total: int, result: CaseResult) -> str:
    models = sorted(
        {
            "/".join(str(c.get(k) or "-") for k in ("cost_tier", "local_family", "local_model"))
            + f"→{c.get('served_model') or ('cache' if c.get('cache_hit') else '?')}"
            for c in result.calls
        }
    )
    detail = f" {result.cause}" if result.cause else ""
    return (
        f"[{index}/{total}] {result.case_id} → {result.category}{detail} "
        f"(primary_outcome={result.primary_outcome}) · provider {result.provider_calls} · "
        f"{result.elapsed_ms / 1000:.1f}s · {', '.join(models) or '모델 기록 없음'}"
    )


async def _collect(run: _Run, ctx: _Context, pending: Sequence[EvalCase], stream: Any) -> None:
    failures_path, _ = output_paths(run.out)
    total = len(pending)
    for index, case in enumerate(pending, start=1):
        try:
            result = await _run_case(case, ctx)
        except Exception as exc:  # noqa: BLE001 — 분류 단계의 결함도 사례 실패로 남기고 계속.
            result = classify_case(
                case,
                None,
                utterance=None,
                receipt=TutorOutputReceipt(),
                ledger=ctx.scope.ledger,
                eos=ctx.eos[case.case_id],
                outer_error=("collector_error", type(exc).__name__),
                elapsed_ms=0,
                run_id=ctx.run_id,
            )
        if result.response is not None:
            _append_line(run.out, dump_responses({case.case_id: result.response}))
            run.responses[case.case_id] = result.response.origin
        if result.failure is not None:
            _append_line(failures_path, json.dumps(result.failure, ensure_ascii=False) + "\n")
        if result.first_prompt is not None:
            run.run_prompts[case.case_id] = result.first_prompt
            run.prompts[case.case_id] = result.first_prompt
        run.counts.add(result)
        run.write()
        print(_progress(index, total, result), file=stream, flush=True)


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError("0보다 커야 한다")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("1 이상이어야 한다")
    return value


def _rate(text: str) -> float:
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("0~1 사이여야 한다")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.ai_quality_live_collect",
        description="P3-78 — P3-10 평가 사례마다 WH-1 primary 러너(라우터 경유·Langfuse)를 돌려 "
        "ai-quality-response/v1 JSONL을 만든다",
    )
    parser.add_argument("--out", type=Path, required=True, help="응답 JSONL 경로")
    parser.add_argument("--eval-set", type=Path, default=None, help="평가셋 JSONL(기본 정본)")
    parser.add_argument("--limit", type=_positive_int, default=None, help="이번 실행 사례 수 상한")
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        help="러너 한 턴 시간 예산(초) — 기본 = 설정 wh1_primary_timeout_seconds(서빙과 같다)",
    )
    parser.add_argument(
        "--min-live-rate",
        type=_rate,
        default=DEFAULT_MIN_LIVE_RATE,
        help=f"완결 파일의 라이브 비율 하한(기본 {DEFAULT_MIN_LIVE_RATE} — 미만이면 exit 4)",
    )
    parser.add_argument("--resume", action="store_true", help="응답 파일에 없는 사례만 이어서 돈다")
    return parser


def _ensure_warning_output() -> None:
    """경고(provider 실패 타입명 등)는 stderr로 — 관측 레코드(INFO)는 섞지 않는다."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


def _config(
    settings: Settings, deps: LiveDeps, turn_timeout: float, outer: float
) -> dict[str, object]:
    """응답을 바꿀 수 있는 설정 — 이 묶음의 지문이 `--resume` 동일성 판정에 쓰인다."""
    return {
        "declared_models": dict(deps.declared_models),
        "turn_timeout_seconds": turn_timeout,
        "outer_timeout_seconds": outer,
        "wh1_prose_rephrase_enabled": settings.wh1_prose_rephrase_enabled,
        "wh1_prose_timeout_seconds": settings.wh1_prose_timeout_seconds,
        "mode_guard_runtime_enabled": settings.mode_guard_runtime_enabled,
        "ollama_request_timeout_s": settings.ollama_request_timeout_s,
        "misconception_semantic_mode": settings.misconception_semantic_mode,
        "misconception_judge_enabled": settings.misconception_judge_enabled,
        "l4_distractor_link_enabled": settings.l4_distractor_link_enabled,
    }


def _unreproduced(settings: Settings) -> list[str]:
    notes: list[str] = []
    if settings.misconception_semantic_mode != "off":
        notes.append(
            f"misconception_semantic_mode={settings.misconception_semantic_mode} — 코치 텍스트 "
            "채널의 의미 매칭 결합은 재현하지 않는다(off 경로만)"
        )
    if settings.misconception_judge_enabled:
        notes.append(
            "misconception_judge_enabled — 코치 텍스트 채널의 LLM judge 필터는 재현하지 않는다"
        )
    return notes


def main(
    argv: Sequence[str] | None = None,
    *,
    deps_factory: Callable[[Settings], LiveDeps] | None = None,
    stream: Any = None,
) -> int:
    """CLI 진입점 — 종료 코드 규약은 모듈 docstring. `deps_factory`는 테스트 주입 좌석이다."""
    args = _parser().parse_args(argv)
    out_stream = stream if stream is not None else sys.stdout
    _ensure_warning_output()
    settings = get_settings()
    out: Path = args.out
    failures_path, run_path = output_paths(out)
    stage = "레지스트리"
    try:
        registry = load_registry()
        stage = "평가셋 적재"
        eval_set = load_eval_set(registry, args.eval_set)
        stage = "기존 산출물 확인"
        existing_paths = [p for p in (out, failures_path, run_path) if p.exists()]
        if existing_paths and not args.resume:
            raise _SetupError(
                f"이전 실행 산출물이 있다({', '.join(str(p) for p in existing_paths)}) — 이어서 "
                "돌리려면 --resume, 새로 돌리려면 다른 --out"
            )
        stage = "좌석 조립"
        deps = (deps_factory or default_deps)(settings)
        turn_timeout = (
            args.timeout if args.timeout is not None else settings.wh1_primary_timeout_seconds
        )
        outer_timeout = turn_timeout + settings.wh1_prose_timeout_seconds + _OUTER_GRACE_SECONDS
        config = _config(settings, deps, turn_timeout, outer_timeout)
        fingerprint = _config_fingerprint(config)
        git = _git_identity(default_repo_root())
        head = git.get("head")
        stage = "기존 산출물 확인"
        existing = (
            _load_existing(
                out,
                run_path,
                eval_set,
                config_fingerprint=fingerprint,
                git_head=head if isinstance(head, str) else None,
            )
            if args.resume
            else _Existing(done={}, prior_runs=[], prompts={})
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        stage = "결정론 기준선"
        eos = build_eos_candidate(eval_set, registry)
        stage = "문제 구조 요약"
        briefs, brief_errors = load_problem_briefs(eval_set)
    except (RegistryError, EvalSetError, CandidateError, _SetupError, OSError, ValueError) as exc:
        print(f"측정 실패 — {stage} 단계: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return EXIT_MEASUREMENT

    done = existing.done
    pending_all = [c for c in eval_set.cases if c.case_id not in done]
    pending = pending_all[: args.limit] if args.limit is not None else pending_all
    run_id = uuid.uuid4().hex
    unreproduced = _unreproduced(settings)
    surface = getattr(deps.trace, "traffic_surface", None)
    record: dict[str, object] = {
        "run_id": run_id,
        "started_at": _utc_now(),
        "finished_at": None,
        "status": "running",
        "git": git,
        "args": {
            "limit": args.limit,
            "timeout": args.timeout,
            "resume": args.resume,
            "min_live_rate": args.min_live_rate,
        },
        "config": config,
        "config_fingerprint": fingerprint,
        "declared_models": dict(deps.declared_models),
        "supplied": list(_SUPPLIED),
        "unsupplied": list(_UNSUPPLIED),
        "unreproduced": unreproduced,
        "problem_briefs": {"found": len(briefs), "load_errors": brief_errors},
        "mode_guard": {
            "configured": settings.mode_guard_runtime_enabled,
            "effective": False,
            "reason": "pack 미공급 — 금지모드 가드 블록은 돌지 않는다(설정값과 무관)",
        },
        "trace": {
            "sink": type(deps.trace).__name__,
            "configured": deps.trace_configured,
            "surface": _plain(surface) if surface is not None else None,
            "emit_warnings": 0,
            "flush": None,
        },
        "cache": "사례마다 새 "
        + str(getattr(deps.cache_factory, "__name__", type(deps.cache_factory).__name__)),
        "pending_before": len(pending_all),
        "exit_code": None,
    }
    run = _Run(
        out=out,
        run_path=run_path,
        eval_set=eval_set,
        prior_runs=existing.prior_runs,
        record=record,
        responses={cid: r.origin for cid, r in done.items()},
        prompts=dict(existing.prompts),
    )
    run.counts.skipped_resume = len(done)
    scope = _Scope()
    ctx = _Context(
        eval_set=eval_set,
        registry=registry,
        eos=eos,
        briefs=briefs,
        settings=settings,
        provider=RecordingProvider(deps.provider, scope),
        trace=RecordingTrace(deps.trace, scope),
        cache_factory=deps.cache_factory,
        scope=scope,
        turn_timeout=turn_timeout,
        outer_timeout=outer_timeout,
        run_id=run_id,
    )
    print(
        f"실행 {run_id[:12]} · 평가셋 {eval_set.source} · sha256 {eval_set.sha256[:12]} · 사례 "
        f"{len(eval_set.cases)} · 이미 수집 {len(done)} · 이번 {len(pending)} · 한 턴 "
        f"{turn_timeout:g}s · 관측 {type(deps.trace).__name__}(구성={deps.trace_configured})",
        file=out_stream,
        flush=True,
    )
    if deps.trace_configured is False:
        print(
            "경고 — 관측 싱크가 구성되지 않았다(Langfuse 키 미설정 → no-op). 수집은 계속하되 "
            "Langfuse 추적은 남지 않는다.",
            file=sys.stderr,
            flush=True,
        )
    for note in unreproduced:
        print(f"경고 — 재현하지 않는 설정 분기: {note}", file=sys.stderr, flush=True)
    emit_counter = _CountingHandler()
    trace_logger = logging.getLogger(_TRACE_LOGGER)
    trace_logger.addHandler(emit_counter)
    try:
        run.write()
        asyncio.run(_collect(run, ctx, pending, out_stream))
        run.record["status"] = "finished"
    except BaseException:
        run.record["status"] = "interrupted"
        run.record["finished_at"] = _utc_now()
        run.write()
        raise
    finally:
        trace_logger.removeHandler(emit_counter)
    trace_record = run.record["trace"]
    assert isinstance(trace_record, dict)
    trace_record["emit_warnings"] = emit_counter.count
    trace_record["flush"] = _flush_trace(deps.trace, deps.trace_configured)
    totals = run.file_totals()
    code = exit_code_for(
        totals, failed_this_run=run.counts.failed, min_live_rate=args.min_live_rate
    )
    run.record["finished_at"] = _utc_now()
    run.record["exit_code"] = code
    try:
        run.write(final=True)
    except OSError as exc:
        print(
            f"측정 실패 — 최종 run.json 쓰기 실패: {type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return EXIT_MEASUREMENT
    c = run.counts
    print(
        f"수집 종료 — 시도 {c.attempted} · 라이브 {c.live} · 하네스 {c.harness} · 강등 "
        f"{c.degraded} · 폴백 {c.fallback} · 미분류 {c.unclassified} · 실패 {c.failed} · 건너뜀 "
        f"{c.skipped_resume} · provider {c.provider_calls} · 캐시 적중 {c.cache_hits} · 관측 flush "
        f"{trace_record['flush']}",
        file=out_stream,
        flush=True,
    )
    print(
        f"파일 전체 — 응답 {totals['responses']}/{totals['cases']} · 남은 사례 "
        f"{totals['remaining']} · 라이브 {totals['live']} (비율 {totals['live_rate']}) · "
        f"유효 표본 상한(서로 다른 첫 프롬프트) {totals['effective_sample_upper_bound']} "
        f"→ exit {code}",
        file=out_stream,
        flush=True,
    )
    if c.failed:
        print(f"실패 원인: {failures_path} — --resume 으로 다시 돈다", file=out_stream, flush=True)
    return code


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
