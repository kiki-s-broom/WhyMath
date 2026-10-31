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

무엇을 부르는가 — 실제 서빙 경로와 같은 것
---------------------------------------
사례마다 `harness.wh1_primary.run_wh1_primary_turn`(코치 `_wh1_primary_decision_or`가 부르는 바로
그 러너)을 한 번 돌린다. LLM 호출은 전부 러너 안의 `LLMTutorPolicy` → `Wh1LlmSeam` →
`l3.pipeline.generate`(`Router().route()` — 라우터 경유) → provider로 간다. 이 도구는 LLM을 직접
부르지 않는다. provider는 서빙과 **같은 팩토리**(`build_cloud_provider` + Ollama)로,
관측은 서빙과 같은 `LangfuseSink`로 조립한다(`ai_quality_live_seat`). 러너가 돌려준 발화는 코치와
같이 **승격 직전 재검증**(`check_deliverable`)을 거친다.

사례 → 러너 입력(평가셋 재료에서 결정론으로 만든다)
-------------------------------------------------
- 힌트 사례(`verdict=None` — 이번 턴에 새 단계가 없다): 학생 발화 = 사례 신호 문장, 풀이 단계 =
  없음, 초기 가설 = 없음, 턴 번호 = 신호의 `turn_count`. 단계 제출이 없으므로 하네스 verify
  의무가 없고, 정책의 명시 발화가 노출 후보가 된다(LLM이 힌트를 직접 쓴다).
- 선택 사례(`verdict=correct|incorrect` — 답을 제출한 턴): 학생 답 = 고른 보기 문자열, 풀이 단계 =
  그 보기 1단계, 초기 가설 = 결정론 오답 매핑 진단(`case_hypotheses`), 턴 번호 = 1. 단계 제출
  턴이라 하네스가 verify를 강제하고, 단계가 하나라 전이 0 → `unverifiable` → 정답 억제 백스톱이
  정책 명시 발화를 막아 하네스 파생 발화가 나간다(서빙과 같은 안전망).
- 공통: 힌트 단계 = 결정론 엔진(`engine_hint_level` — 코치가 넘기는 `decision.hint_level`과 같은
  함수), 튜터 내용 요약 = 개념 1개(code = 사례 `concept_id`, 이름 = 레지스트리 `name_ko`).

결정론 후보(`eos-deterministic`)와 같은 것 / 다른 것
-------------------------------------------------
**같은 것** — 구조체 빌더(`wh1_tutor_output.build_tutor_output`)와 그 서버 측 재료 전부: 검증 판정
= 사례 라벨(`case.verdict` — 코치의 답 판정에 해당), 진단 = `case_hypotheses`(LLM은 진단을 정하지
않는다), 개념 = 사례 `concept_id`, 힌트 단계 = `engine_hint_level`, `referenced_concept_ids` = 빈
튜플(둘 다 — 러너는 도구 트레이스를 돌려주지 않으며, 본문 속 개념 참조는 판정기가 본문에서 직접
추출한다).
**다른 것** — 러너가 서빙한 구조체에서 가져오는 세 필드: 발화 본문(`explanation`), 발화
저자(`explanation_source` — 정책 명시 발화·프로즈면 `llm`, 하네스 파생이면 `harness_template`),
응답 전략(`response_strategy` — LLM이 고른 `end_turn` 행위 유형. 발화와 같은 행위에서 나오므로
발화만 바꾸고 전략을 결정론 것으로 두면 "출제 발화 + 힌트 전략" 같은 모순 구조체가 된다).
다음 행동은 같은 빌더 규칙으로 전략·판정에서 유도된다. 힌트 단계도 다르다 — 결정론 후보는 L3
공백을 L2로 낮춰 **표시**하지만(P3-77), 라이브는 엔진 단계를 그대로 싣는다(코치와 같다).
**재조립 거부** — 사례 판정으로 재조립한 구조체를 P3-09가 거부하면(예: 오답 판정 턴에 격려 전략),
러너가 실제로 서빙한 구조체(하네스 판정 기준)를 그대로 싣고 주석을 단다 — 판정기는 원시 dict를
그대로 판정하고 P3-09 차단 여부를 따로 적는다.

사례 결말 분류 — 폴백을 라이브로 위장하지 않는다
---------------------------------------------
러너가 내는 관측 레코드(`wh1_shadow.record_logger` — 서빙과 같은 `primary_outcome` 닫힌 어휘)를
사례마다 붙잡아 분류한다. 응답 파일의 `origin`이 결말을 말한다.

- `wh1-live` — 발화 반환 + `primary_outcome=adopted`. 응답 파일에 쓴다.
- `wh1-live:degraded` — 발화 반환 + `fallback_llm_degraded`·`fallback_mode_guard`(학생이 받은
  것이 하네스 결정론 발화다). 응답 파일에 주석과 함께 쓴다.
- `wh1-live:fallback` — 러너 `None`(예산 소진·발화 없음·프로즈 게이트·출력 스키마) 또는 승격
  재검증 거부. 서빙처럼 결정론 폴백 = 이 사례의 `eos-deterministic` 응답을 주석과 함께 쓴다.
- `wh1-live:unclassified` — 발화는 반환됐는데 관측 레코드가 없거나 어휘 밖. 주석과 함께 쓴다.
- 실패 — provider 예외(타입명·HTTP 상태·본문 일부·타임아웃) · 러너 중단(`fallback_timeout`·
  `fallback_exception`) · 바깥 타임아웃 · 수집기 예외. **응답 파일에 쓰지 않고** 실패 파일에 쓴다.

실패는 응답을 쓰지 않는다 — provider 예외가 난 턴은 정책이 안전 강등으로 흡수해 결정론 발화를
내지만, 그것은 튜터 품질이 아니라 인프라 실패의 산물이다. 응답이 없는 사례는 평가기가 "응답 누락"
실패로 센다(통과로 접지 않는다). `--resume`이 응답 파일에 없는 사례만 다시 돈다.

산출물 3종(평가셋·모델·시각 식별 — 측정·수집 도구 실패 경로 규칙)
-----------------------------------------------------------
- `<out>` — `ai-quality-response/v1` JSONL(`ai_quality_candidates.load_responses`로 그대로 읽힌다 ·
  메타 줄 없음). 사례마다 **즉시** 한 줄 쓰고 flush·fsync한다(중간에 멈춰도 쓴 것은 남는다).
- `<out>.failures.jsonl` — 실패 1건 1줄(사례 id · 종류 · 예외 타입명 연쇄 · HTTP 상태 ·
  본문/메시지 일부(300자·키 모양 문자열 가림) · 타임아웃·취소 여부 · 실패한 호출의 라우터 좌석).
  이어 쓰기(이력).
- `<out>.run.json` — 실행 식별: 평가셋 경로·sha256 · git HEAD·dirty · 시작/끝 시각(UTC) · 설정
  (타임아웃·프로즈·금지모드 가드) · 선언 모델 핀(셀렉터 좌석·핀·로컬 매트릭스) · **관측 모델**
  (트레이스에서 센 실제 좌석·모델 id별 호출 수) · 시도/라이브/강등/폴백/미분류/실패/건너뜀 건수 ·
  `primary_outcome` 분포 · 관측 싱크 구성 여부·flush 결과. 시작 시 `running`으로 쓰고 사례마다
  갱신(원자적 교체)하므로 중단돼도 어디까지 갔는지 남는다. `--resume`이면 이전 실행 기록에 덧붙인다.

종료 코드
---------
- 0 — 이번 실행이 시도한 사례가 전부 응답으로 끝났고(폴백·강등은 표기된 채 포함) 실패 0, 라이브 ≥ 1
  (시도할 사례가 남지 않은 `--resume`은 파일에 라이브 응답이 1건 이상이면 0)
- 1 — 측정 실패: 적재·준비 실패(레지스트리·평가셋·기존 산출물 충돌·손상·평가셋 지문 불일치·좌석
  조립) **또는 공허 수집** — 이번 실행이 사례를 시도했는데 라이브(`adopted`) 0건이거나, 응답 파일
  전체에 라이브 응답이 0건. 폴백·강등만으로 채운 파일을 라이브 측정으로 내놓지 않는다.
- 2 — 인자 오류(argparse).
- 3 — 부분 수집: 라이브 ≥ 1이지만 실패가 1건 이상 → `--resume`으로 다시 돌린다(실패 파일에 원인).

프라이버시·비용
---------------
평가 사례는 합성(학생 데이터 0)이지만 응답 원문은 **평가 산출물(`<out>`)에만** 둔다 — 진행 출력·
실패 파일·`run.json`·관측 레코드에는 싣지 않는다(실패 파일의 본문 일부는 provider 오류 응답이지
튜터 발화가 아니다). 관측 표면은 `probe`(학생 대면 비용 표본과 분리). 캐시는 실행마다 새
`InMemoryCache` — 이전 실행·서빙 Redis의 응답이 이번 측정으로 적중하지 않는다(같은 실행 안의 동일
프롬프트 적중은 서빙과 같은 동작이며 `run.json`이 적중 수를 센다).

타임아웃
--------
모든 외부 호출에 시간 상한이 있다: provider 단일 호출(설정의 Ollama·클라우드 요청 타임아웃) ·
러너 한 턴(`--timeout`, 기본 = 서빙 설정 `wh1_primary_timeout_seconds`) · 바깥 방어선(한 턴 +
프로즈 예산 + 10초 — 러너 밖에서 멈춘 경우) · git 조회 5초 · 관측 flush 30초(데몬 스레드).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
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
    case_hypotheses,
    dump_responses,
    engine_hint_level,
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
    TutorContentSummary,
    build_tutor_content_summary,
)
from whymath_backend.harness.wh1_tutor_output import (
    TutorOutputReceipt,
    TutorTurnOutput,
    build_tutor_output,
    check_deliverable,
)
from whymath_backend.l3.interfaces import (
    CacheBackend,
    InMemoryCache,
    LLMProvider,
    NamedEventSink,
    TraceSink,
)
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis

__all__ = [
    "DEGRADED_ORIGIN",
    "EXIT_MEASUREMENT",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "FAILURE_SCHEMA",
    "FALLBACK_ORIGIN",
    "LIVE_ORIGIN",
    "RUN_SCHEMA",
    "UNCLASSIFIED_ORIGIN",
    "CaseLedger",
    "LiveDeps",
    "LiveTurnInputs",
    "RecordingProvider",
    "RecordingTrace",
    "default_deps",
    "live_turn_inputs",
    "main",
    "output_paths",
]

LIVE_ORIGIN: Final = "wh1-live"
DEGRADED_ORIGIN: Final = "wh1-live:degraded"
FALLBACK_ORIGIN: Final = "wh1-live:fallback"
UNCLASSIFIED_ORIGIN: Final = "wh1-live:unclassified"
FAILURE_SCHEMA: Final = "ai-quality-live-failure/v1"
RUN_SCHEMA: Final = "ai-quality-live-run/v1"

EXIT_OK: Final = 0
EXIT_MEASUREMENT: Final = 1
EXIT_PARTIAL: Final = 3

_EXCERPT_CHARS: Final = 300
_OUTER_GRACE_SECONDS: Final = 10.0
_GIT_TIMEOUT_SECONDS: Final = 5.0
_FLUSH_TIMEOUT_SECONDS: Final = 30.0
_CHAIN_LIMIT: Final = 5

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
"""관측 트레이스에서 사례 회계로 옮기는 필드 — 라우팅·모델 식별뿐(프롬프트·응답 텍스트는 원래
없다)."""

_MODEL_KEY: Final = ("cost_tier", "local_family", "local_model", "served_model", "cloud_seat")

_SECRET_LIKE: Final = re.compile(r"(sk-[A-Za-z0-9_\-]{6,}|pk-[A-Za-z0-9_\-]{6,}|Bearer\s+\S+)")

logger = logging.getLogger("whymath.harness.ai_quality_live_collect")


# ──────────────────────────────────────────────────────────────────────────
# 사례 회계 — 래퍼·싱크·관측 캡처가 이번 사례 몫을 여기 모은다
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class CaseLedger:
    """사례 1건 동안 모인 것 — provider 예외·트레이스 호출·러너 관측 레코드."""

    faults: list[dict[str, object]] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)


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


class RecordingProvider:
    """안쪽 provider로 **그대로 전달**하며 이번 사례의 예외를 기록한다(결정·인자 무변경).

    이 래퍼는 호출을 만들지 않는다 — `l3.pipeline`이 라우터 결정(`decision`)을 실어 부른 것을
    받은 그대로 넘긴다. 선택 인자는 받은 것만 넘긴다(파이프라인의 "있을 때만 전달" 관례 — 그
    인자를 받지 않는 provider·대역이 그대로 동작하게). 좌석 표면(`cloud_seat` 등)은 안쪽 것을
    그대로 보인다(`__getattr__`) — 파이프라인의 원가 좌석 판정(`served_cloud_seat`)이 래퍼 때문에
    바뀌지 않게.
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


@contextmanager
def _capture_observations(sink: list[dict[str, object]]) -> Iterator[None]:
    """관측 로거에 붙잡기 핸들러를 잠시 단다 — INFO가 꺼져 있으면 그동안만 켜고 되돌린다."""
    handler = _ObservationHandler(sink)
    previous = _observation_logger.level
    if not _observation_logger.isEnabledFor(logging.INFO):
        _observation_logger.setLevel(logging.INFO)
    _observation_logger.addHandler(handler)
    try:
        yield
    finally:
        _observation_logger.removeHandler(handler)
        _observation_logger.setLevel(previous)


# ──────────────────────────────────────────────────────────────────────────
# 사례 → 러너 입력
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiveTurnInputs:
    """러너 한 턴 입력 — 평가셋 재료에서 결정론으로 만든다(모듈 docstring '사례 → 러너 입력')."""

    student_solution: str
    solution_steps: tuple[str, ...]
    active_hypotheses: tuple[MisconceptionHypothesis, ...]
    hint_level: int
    turn_index: int
    problem_id: str
    tutor_content: TutorContentSummary


def live_turn_inputs(case: EvalCase, eval_set: EvalSet, registry: Registry) -> LiveTurnInputs:
    material = eval_set.materials[case.problem_id]
    content = build_tutor_content_summary(
        concept_code=case.concept_id,
        concept_name=registry.concepts[case.concept_id].name_ko,
        skills=(),
        skill_total=0,
        problem=None,
        pack=None,
    )
    if case.kind == KIND_HINT:
        assert case.signals is not None
        return LiveTurnInputs(
            student_solution=case.signals.student_input,
            solution_steps=(),
            active_hypotheses=(),
            hint_level=engine_hint_level(case),
            turn_index=case.signals.turn_count,
            problem_id=str(material.problem_uuid),
            tutor_content=content,
        )
    assert case.selected_choice_index is not None
    chosen = material.choices[case.selected_choice_index]
    return LiveTurnInputs(
        student_solution=chosen,
        solution_steps=(chosen,),
        active_hypotheses=case_hypotheses(case, eval_set),
        hint_level=engine_hint_level(case),
        turn_index=1,
        problem_id=str(material.problem_uuid),
        tutor_content=content,
    )


# ──────────────────────────────────────────────────────────────────────────
# 결말 분류
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    """live / degraded / fallback / unclassified / failed."""
    response: TutorResponse | None
    failure: dict[str, object] | None
    primary_outcome: str | None
    elapsed_ms: int
    calls: tuple[dict[str, object], ...]
    rebuild_rejected: bool = False


def _primary_outcome(observations: Sequence[Mapping[str, object]]) -> str | None:
    for record in reversed(observations):
        if record.get("primary") is True:
            value = record.get("primary_outcome")
            return value if isinstance(value, str) else None
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


def _failure(
    case_id: str,
    kind: str,
    *,
    ledger: CaseLedger,
    outcome: str | None,
    elapsed_ms: int,
    exc_type: str | None = None,
    timeout: bool = False,
) -> dict[str, object]:
    any_timeout = timeout or any(f.get("timeout") is True for f in ledger.faults)
    first_fault = ledger.faults[0].get("exc_type") if ledger.faults else None
    return {
        "schema": FAILURE_SCHEMA,
        "case_id": case_id,
        "at": _utc_now(),
        "kind": kind,
        "exc_type": exc_type if exc_type is not None else first_fault,
        "timeout": any_timeout,
        "primary_outcome": outcome,
        "faults": list(ledger.faults),
        "llm_calls_recorded": len(ledger.calls),
        "elapsed_ms": elapsed_ms,
    }


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
) -> CaseResult:
    """러너 결과·회계 → 결말 1건(모듈 docstring 결말 표). 실패는 응답을 만들지 않는다."""
    outcome = _primary_outcome(ledger.observations)
    calls = tuple(ledger.calls)

    def _failed(kind: str, *, exc_type: str | None = None, timeout: bool = False) -> CaseResult:
        record = _failure(
            case.case_id,
            kind,
            ledger=ledger,
            outcome=outcome,
            elapsed_ms=elapsed_ms,
            exc_type=exc_type,
            timeout=timeout,
        )
        return CaseResult(case.case_id, "failed", None, record, outcome, elapsed_ms, calls)

    def _fallback(reason: str) -> CaseResult:
        note = f"primary 폴백({reason}) — 서빙과 같은 결정론 폴백: {CANDIDATE_EOS} 응답을 싣는다"
        if eos.note:
            note = f"{note} · 결정론 주석: {eos.note}"
        response = replace(eos, origin=FALLBACK_ORIGIN, note=note)
        return CaseResult(case.case_id, "fallback", response, None, outcome, elapsed_ms, calls)

    # 순서: 바깥 방어선 → 러너 중단(타임아웃이 비행 중 호출을 끊었으면 그 취소도 faults에 함께
    # 실린다) → provider 예외(정책이 강등으로 흡수해 턴은 끝났어도 인프라 실패다) → 폴백 → 응답.
    if outer_error is not None:
        kind, exc_type = outer_error
        return _failed(kind, exc_type=exc_type, timeout=kind == "outer_timeout")
    if outcome in _ABORTED_OUTCOMES:
        return _failed(
            "runner_timeout" if outcome == "fallback_timeout" else "runner_exception",
            timeout=outcome == "fallback_timeout",
        )
    if ledger.faults:
        return _failed("provider_error")
    if utterance is None or inputs is None:
        return _fallback(outcome or "결말 미상 — 관측 레코드 없음")
    rejection = check_deliverable(
        receipt.output, utterance=utterance, known_concept_ids=frozenset({case.concept_id})
    )
    if rejection is not None or receipt.output is None:
        return _fallback(f"승격 직전 재검증 거부({rejection})")
    tutor_output, rebuild_note = _rebuild(case, inputs, receipt.output)
    if outcome == PRIMARY_ADOPTED:
        category, origin, note = "live", LIVE_ORIGIN, rebuild_note
    elif outcome in _DEGRADED_OUTCOMES:
        category, origin = "degraded", DEGRADED_ORIGIN
        note = f"하네스 결정론 발화({outcome}) — LLM 발화가 아니다"
        if rebuild_note:
            note = f"{note} · {rebuild_note}"
    else:
        category, origin = "unclassified", UNCLASSIFIED_ORIGIN
        note = f"결말 미분류(primary_outcome={outcome!r}) — 라이브로 세지 않는다"
        if rebuild_note:
            note = f"{note} · {rebuild_note}"
    response = TutorResponse(
        case_id=case.case_id, tutor_output=tutor_output, origin=origin, note=note
    )
    return CaseResult(
        case.case_id,
        category,
        response,
        None,
        outcome,
        elapsed_ms,
        calls,
        rebuild_rejected=rebuild_note is not None,
    )


# ──────────────────────────────────────────────────────────────────────────
# 의존 조립
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiveDeps:
    """한 실행의 L3 의존 — provider·관측·캐시 + 선언 모델 핀(실행 식별용)."""

    provider: LLMProvider
    trace: TraceSink
    cache: CacheBackend
    declared_models: Mapping[str, object]
    trace_configured: bool | None


def default_deps(settings: Settings) -> LiveDeps:
    """서빙과 같은 팩토리(`ai_quality_live_seat`) + 실행마다 새 인메모리 캐시."""
    trace = build_live_trace()
    return LiveDeps(
        provider=build_live_provider(settings),
        trace=trace,
        cache=InMemoryCache(),
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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_existing(
    out: Path, run_path: Path, eval_set: EvalSet
) -> tuple[dict[str, TutorResponse], list[object]]:
    """`--resume`: 이미 쓴 응답과 이전 실행 기록. 손상·평가셋 불일치는 거부(증거를 덮지 않는다)."""
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
    runs: list[object] = []
    if run_path.exists():
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
    return done, runs


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
        status = _git("status", "--porcelain")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"head": None, "dirty": None, "error": type(exc).__name__}
    return {"head": head, "dirty": None if status is None else bool(status)}


def _flush_trace(trace: TraceSink) -> str:
    """관측 flush를 데몬 스레드로 — 네트워크가 멈춰도 프로세스 종료를 막지 않는다."""
    flush = getattr(trace, "flush", None)
    if not callable(flush):
        return "not_supported"
    box: dict[str, str] = {}

    def _run() -> None:
        try:
            flush()
            box["result"] = "ok"
        except Exception as exc:  # noqa: BLE001 — flush 실패는 기록하고 계속(타입명 포함).
            box["result"] = f"error:{type(exc).__name__}"

    worker = threading.Thread(target=_run, name="aq-live-trace-flush", daemon=True)
    worker.start()
    worker.join(_FLUSH_TIMEOUT_SECONDS)
    if worker.is_alive():
        return "timeout"
    return box.get("result", "error:unknown")


# ──────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _RunCounts:
    attempted: int = 0
    live: int = 0
    degraded: int = 0
    fallback: int = 0
    unclassified: int = 0
    failed: int = 0
    skipped_resume: int = 0
    rebuild_rejected: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    provider_faults: int = 0
    primary_outcomes: Counter[str] = field(default_factory=Counter)
    models: Counter[tuple[object, ...]] = field(default_factory=Counter)

    def add(self, result: CaseResult) -> None:
        self.attempted += 1
        setattr(self, result.category, getattr(self, result.category) + 1)
        self.rebuild_rejected += int(result.rebuild_rejected)
        self.primary_outcomes[result.primary_outcome or "none"] += 1
        if result.failure is not None:
            faults = result.failure.get("faults")
            self.provider_faults += len(faults) if isinstance(faults, list) else 0
        for call in result.calls:
            self.llm_calls += 1
            if call.get("cache_hit") is True:
                self.cache_hits += 1
            self.models[tuple(call.get(key) for key in _MODEL_KEY)] += 1

    def to_json(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "live": self.live,
            "degraded": self.degraded,
            "fallback": self.fallback,
            "unclassified": self.unclassified,
            "failed": self.failed,
            "skipped_resume": self.skipped_resume,
            "rebuild_rejected": self.rebuild_rejected,
            "llm_calls_recorded": self.llm_calls,
            "cache_hits": self.cache_hits,
            "provider_faults": self.provider_faults,
            "live_rate": (self.live / self.attempted) if self.attempted else None,
        }


@dataclass
class _Run:
    """한 실행의 상태 — 사례마다 `run.json`을 다시 쓴다."""

    out: Path
    run_path: Path
    eval_set: EvalSet
    prior_runs: list[object]
    record: dict[str, object]
    counts: _RunCounts = field(default_factory=_RunCounts)
    origins_in_file: Counter[str] = field(default_factory=Counter)

    def write(self) -> None:
        self.record["counts"] = self.counts.to_json()
        self.record["primary_outcomes"] = dict(sorted(self.counts.primary_outcomes.items()))
        self.record["observed_models"] = [
            {**dict(zip(_MODEL_KEY, key, strict=True)), "calls": n}
            for key, n in self.counts.models.most_common()
        ]
        payload: dict[str, object] = {
            "schema": RUN_SCHEMA,
            "responses": str(self.out),
            "eval_set": {
                "source": self.eval_set.source,
                "sha256": self.eval_set.sha256,
                "cases": len(self.eval_set.cases),
            },
            "file_totals": {
                "responses": sum(self.origins_in_file.values()),
                "by_origin": dict(sorted(self.origins_in_file.items())),
            },
            "runs": [*self.prior_runs, self.record],
        }
        _write_json_atomic(self.run_path, payload)


def exit_code_for(counts: _RunCounts, live_in_file: int) -> int:
    """종료 코드 규약(모듈 docstring) — 공허 수집은 1, 부분 수집은 3."""
    if counts.attempted > 0 and counts.live == 0:
        return EXIT_MEASUREMENT
    if live_in_file == 0:
        return EXIT_MEASUREMENT
    if counts.failed > 0:
        return EXIT_PARTIAL
    return EXIT_OK


@dataclass(frozen=True)
class _Context:
    eval_set: EvalSet
    registry: Registry
    eos: Mapping[str, TutorResponse]
    provider: LLMProvider
    trace: TraceSink
    cache: CacheBackend
    scope: _Scope
    turn_timeout: float
    outer_timeout: float


async def _run_case(case: EvalCase, ctx: _Context) -> CaseResult:
    ledger = CaseLedger()
    ctx.scope.ledger = ledger
    receipt = TutorOutputReceipt()
    started = time.monotonic()
    utterance: str | None = None
    inputs: LiveTurnInputs | None = None
    outer_error: tuple[str, str | None] | None = None
    try:
        inputs = live_turn_inputs(case, ctx.eval_set, ctx.registry)
        with _capture_observations(ledger.observations):
            utterance = await asyncio.wait_for(
                run_wh1_primary_turn(
                    student_solution=inputs.student_solution,
                    solution_steps=list(inputs.solution_steps),
                    active_hypotheses=list(inputs.active_hypotheses),
                    provider=ctx.provider,
                    cache=ctx.cache,
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
    )


def _progress(index: int, total: int, result: CaseResult) -> str:
    models = sorted(
        {
            "/".join(str(c.get(k) or "-") for k in ("cost_tier", "local_family", "local_model"))
            + f"→{c.get('served_model') or ('cache' if c.get('cache_hit') else '?')}"
            for c in result.calls
        }
    )
    kind = f" {result.failure.get('kind')}" if result.failure is not None else ""
    return (
        f"[{index}/{total}] {result.case_id} → {result.category}{kind} "
        f"(primary_outcome={result.primary_outcome}) · llm {len(result.calls)} · "
        f"{result.elapsed_ms / 1000:.1f}s · {', '.join(models) or '모델 기록 없음'}"
    )


async def _collect(run: _Run, ctx: _Context, pending: Sequence[EvalCase], stream: Any) -> None:
    failures_path, _ = output_paths(run.out)
    total = len(pending)
    for index, case in enumerate(pending, start=1):
        try:
            result = await _run_case(case, ctx)
        except Exception as exc:  # noqa: BLE001 — 분류 단계의 결함도 사례 실패로 남기고 계속.
            result = CaseResult(
                case.case_id,
                "failed",
                None,
                _failure(
                    case.case_id,
                    "collector_error",
                    ledger=ctx.scope.ledger,
                    outcome=None,
                    elapsed_ms=0,
                    exc_type=type(exc).__name__,
                ),
                None,
                0,
                tuple(ctx.scope.ledger.calls),
            )
        if result.response is not None:
            _append_line(run.out, dump_responses({case.case_id: result.response}))
            run.origins_in_file[result.response.origin] += 1
        if result.failure is not None:
            _append_line(failures_path, json.dumps(result.failure, ensure_ascii=False) + "\n")
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
        existing = [p for p in (out, failures_path, run_path) if p.exists()]
        if existing and not args.resume:
            raise _SetupError(
                f"이전 실행 산출물이 있다({', '.join(str(p) for p in existing)}) — 이어서 돌리려면 "
                "--resume, 새로 돌리려면 다른 --out"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        done, prior_runs = _load_existing(out, run_path, eval_set) if args.resume else ({}, [])
        stage = "결정론 기준선"
        eos = build_eos_candidate(eval_set, registry)
        stage = "좌석 조립"
        deps = (deps_factory or default_deps)(settings)
    except (RegistryError, EvalSetError, CandidateError, _SetupError, OSError, ValueError) as exc:
        print(f"측정 실패 — {stage} 단계: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return EXIT_MEASUREMENT

    turn_timeout = (
        args.timeout if args.timeout is not None else settings.wh1_primary_timeout_seconds
    )
    outer_timeout = turn_timeout + settings.wh1_prose_timeout_seconds + _OUTER_GRACE_SECONDS
    pending_all = [c for c in eval_set.cases if c.case_id not in done]
    pending = pending_all[: args.limit] if args.limit is not None else pending_all
    record: dict[str, object] = {
        "started_at": _utc_now(),
        "finished_at": None,
        "status": "running",
        "git": _git_identity(default_repo_root()),
        "args": {"limit": args.limit, "timeout": args.timeout, "resume": args.resume},
        "settings": {
            "turn_timeout_seconds": turn_timeout,
            "outer_timeout_seconds": outer_timeout,
            "wh1_primary_timeout_seconds": settings.wh1_primary_timeout_seconds,
            "wh1_prose_rephrase_enabled": settings.wh1_prose_rephrase_enabled,
            "wh1_prose_timeout_seconds": settings.wh1_prose_timeout_seconds,
            "mode_guard_runtime_enabled": settings.mode_guard_runtime_enabled,
            "ollama_request_timeout_s": settings.ollama_request_timeout_s,
        },
        "declared_models": dict(deps.declared_models),
        "trace": {
            "sink": type(deps.trace).__name__,
            "configured": deps.trace_configured,
            "surface": "probe",
        },
        "cache": type(deps.cache).__name__,
        "pending_before": len(pending_all),
        "exit_code": None,
    }
    run = _Run(out=out, run_path=run_path, eval_set=eval_set, prior_runs=prior_runs, record=record)
    run.counts.skipped_resume = len(done)
    run.origins_in_file.update(r.origin for r in done.values())
    scope = _Scope()
    ctx = _Context(
        eval_set=eval_set,
        registry=registry,
        eos=eos,
        provider=RecordingProvider(deps.provider, scope),
        trace=RecordingTrace(deps.trace, scope),
        cache=deps.cache,
        scope=scope,
        turn_timeout=turn_timeout,
        outer_timeout=outer_timeout,
    )
    print(
        f"평가셋 {eval_set.source} · sha256 {eval_set.sha256[:12]} · 사례 {len(eval_set.cases)} · "
        f"이미 수집 {len(done)} · 이번 {len(pending)} · 한 턴 {turn_timeout:g}s · "
        f"관측 {type(deps.trace).__name__}(구성={deps.trace_configured})",
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
    run.write()
    try:
        asyncio.run(_collect(run, ctx, pending, out_stream))
        run.record["status"] = "finished"
    except BaseException:
        run.record["status"] = "interrupted"
        run.record["finished_at"] = _utc_now()
        run.write()
        raise
    run.record["trace_flush"] = _flush_trace(deps.trace)
    live_in_file = run.origins_in_file.get(LIVE_ORIGIN, 0)
    code = exit_code_for(run.counts, live_in_file)
    run.record["finished_at"] = _utc_now()
    run.record["exit_code"] = code
    run.write()
    c = run.counts
    print(
        f"수집 종료 — 시도 {c.attempted} · 라이브 {c.live} · 강등 {c.degraded} · 폴백 {c.fallback} "
        f"· 미분류 {c.unclassified} · 실패 {c.failed} · 건너뜀 {c.skipped_resume} · 파일 라이브 "
        f"{live_in_file} · 관측 flush {run.record['trace_flush']} → exit {code}",
        file=out_stream,
        flush=True,
    )
    if c.failed:
        print(f"실패 원인: {failures_path} — --resume 으로 다시 돈다", file=out_stream, flush=True)
    return code


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
