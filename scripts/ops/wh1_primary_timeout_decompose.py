#!/usr/bin/env python3
"""WH-1 primary 한 턴의 시간 예산이 어디서 소진되는지 구간별로 잰다 (OPS-141 · Phaiakes9 실측 도구).

왜 이 도구가 필요한가
--------------------
2026-10-12 라이브 실측에서 15요청 중 14턴이 `wh1_primary_timeout_seconds`(기본 15초)에 걸려 결정론
템플릿으로 폴백했다. OPS-134가 관측 레코드에 `elapsed_ms`·`llm_ms_total`·`llm_calls`·
`llm_calls_finished`를 실었지만, 그 숫자만으로는 원인을 가를 수 없다 — **`llm_ms_total`은
`seam.generate` 전체를 감싸는 타이머라 Redis 캐시 get/set 대기가 "LLM 호출 시간"에 섞여 들어간다**
(`harness/wh1_llm_policy.py` `next_action` ↔ `l3/pipeline.py` `cache.get`→생성→`cache.set`).
그래서 이 도구는 프로바이더와 캐시를 **각각** 감싸 호출마다 시작·끝 시각을 기록한다. 프로덕션 코드는
한 줄도 바꾸지 않는다(래퍼는 이 파일에만 있다).

무엇을 재는가 (한 턴 = `run_wh1_primary_turn` 한 번, 서버·DB 불요)
-------------------------------------------------------------------
- 캐시 get/set 구간(Redis 강등으로 미스 처리된 연산은 `degraded` 표시)
- 프로바이더(Ollama) 생성 구간
- 나머지 = 턴 소요 − 캐시 − 프로바이더 (프롬프트 조립·파싱·도구 실행·트레이스 기록. 이 잔여가 작으면
  그 안의 어떤 단계도 클 수 없다는 산술이 된다 — 별도 계측을 더할지는 이 숫자가 정한다)
- 타임아웃 취소 시점에 **무엇이 진행 중이었는지**(`CancelledError`로 닫힌 구간의 종류)
- OPS-134 관측 레코드(`whymath.harness.wh1_shadow.record` 로거)를 가로채 자기 계측과 대조한다 —
  `cache_get` 구간 수 == `llm_calls`가 아니면 래퍼가 걸리지 않은 것이라 `MISMATCH`로 표시한다.

후보 조립(`assemble_probe_candidate_pool`)은 **재지 않는다**: 그 호출은 `asyncio.wait_for` 바깥이라
15초 예산을 소모하지 않고(`harness/wh1_primary.py`), 이 도구는 DB 세션을 만들지 않는다. 예산 안의
비LLM 구간(도구 실행 등)은 위 "나머지"에 들어온다.

캐시 키는 턴마다 고유 접두를 붙인다 — 적중하면 LLM 호출이 생략돼 소요가 위장으로 낮아지기 때문이다.
Redis 왕복 비용(get 미스 + set 쓰기)은 그대로 발생한다. 적중 효과는 이 측정의 범위 밖이다.

조건 3종 (`--condition`) — 선언한 조건이 실제와 다르면 **측정하지 않고 거부**한다
- `redis-down`: 실서비스 기본 `redis_url`(또는 `--redis-url`)에 실제 `RedisCache`.
  연산이 전부 강등이어야 한다.
- `redis-up`: 같은 `RedisCache`가 응답하는 Redis를 가리킨다. 연산이 전부 정상이어야 한다.
- `memory`: `InMemoryCache`(대조군 — 캐시 비용이 0인 상태).
조건 확인은 시작 시 캐시 프로브(`--cache-probe-ops`회 get)로 한다 — 같은 코드 경로를 그대로 쓴다.

기록 원칙(CLAUDE.md 「측정·수집 도구를 성공 경로만 보고 설계 금지」)
- 한 줄 = 한 사건, 쓸 때마다 flush+fsync — 도중에 멈춰도 증거가 남는다(footer 없음 = 중단).
- 실패는 예외 *타입명*으로 남긴다(메시지는 프롬프트·학생 발화를 담을 수 있어 제외).
- 모든 레코드에 `run_id` — 집계는 지정한 실행분만 읽는다. 외부 호출(Ollama HTTP·git)에는
  타임아웃.
- 합성 시나리오뿐이다(학생 데이터 0). 클라우드 호출 0 — 정책은 `classify`/GENERAL/FAST/LOCAL로
  라우팅된다.

사용
  python scripts/ops/wh1_primary_timeout_decompose.py measure --condition redis-down --out DIR
         [--reps 3] [--timeout-seconds 15] [--cold] [--redis-url URL] [--cache-probe-ops 6]
  python scripts/ops/wh1_primary_timeout_decompose.py summarize --out DIR
         --run-id ID [--run-id ID ...]
종료: 0 정상 / 1 측정 실패(증거는 남음) / 2 인자·사전조건 오류(아무것도 측정하지 않음)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TOOL_VERSION = 1
_RECORD_FILE = "decompose.jsonl"
_OBS_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"  # OPS-134 관측 레코드가 나오는 로거

CONDITIONS = ("redis-down", "redis-up", "memory")

# 합성 시나리오 — (라벨, 학생 입력, 풀이 단계). `scripts/demo/wh1_primary_probe.py`의 3케이스에
# 풀이 없는 단순 턴을 더했다. 학생 데이터가 아니라 고정 문자열이다.
SCENARIOS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("correct_chain", "x=2", ("2x+3=7", "2x=4", "x=2")),
    ("wrong_chain", "x=1", ("2x+3=7", "2x=5", "x=1")),
    ("natural_form", "x=2", ("2x+3=7", "x=(7-3)/2=2")),
    ("simple_turn", "네, 알겠어요", ()),
)

# 한 구간이 턴 소요의 이 비율 이상이면 그 턴의 지배 원인으로 본다. 미만이면 지배 원인 없음.
DOMINANT_SHARE = 0.5

# 예산 후보 — 「이 예산이면 몇 %의 턴이 넘는가」 표에 쓴다(③ 재판정 재료).
BUDGET_CANDIDATES_S = (10.0, 15.0, 20.0, 30.0, 60.0)

_HTTP_TIMEOUT_S = 5.0  # Ollama /api/ps·unload HTTP 호출 상한
_GIT_TIMEOUT_S = 10.0
_TURN_WALL_MARGIN_S = 30.0  # 턴 하나의 도구 측 벽시계 상한 = 턴 예산 + 이 여유(Ollama 무응답 방어)


# ──────────────────────────────────────────────────────────────────────────
# 구간 기록 — 프로바이더·캐시 래퍼가 공유한다
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Span:
    """한 구간. `end_ms`가 None이면 아직 열려 있는 것(정상 경로에선 항상 닫힌다)."""

    kind: str  # "cache_get" | "cache_set" | "provider"
    start_ms: float
    end_ms: float | None = None
    outcome: str = "open"  # "ok" 또는 예외 타입명(취소는 "CancelledError")
    degraded: bool = False  # 캐시 연산이 강등(실패→미스/no-op)으로 끝났는가
    hit: bool | None = None  # cache_get만: 적중 여부
    model: str | None = None  # provider만: 라우터가 고른 로컬 모델 ID

    @property
    def duration_ms(self) -> float:
        return 0.0 if self.end_ms is None else max(0.0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_ms": round(self.start_ms, 1),
            "end_ms": None if self.end_ms is None else round(self.end_ms, 1),
            "outcome": self.outcome,
            "degraded": self.degraded,
            "hit": self.hit,
            "model": self.model,
        }


class SpanRecorder:
    """한 턴의 구간 목록. `start_turn`이 시각 0을 정한다. 시계는 주입 가능(테스트용)."""

    def __init__(self, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._t0 = clock()
        self.spans: list[Span] = []

    def start_turn(self) -> None:
        self._t0 = self._clock()
        self.spans = []

    def now_ms(self) -> float:
        return (self._clock() - self._t0) * 1000.0

    def open(self, kind: str) -> Span:
        span = Span(kind=kind, start_ms=self.now_ms())
        self.spans.append(span)
        return span

    def close(self, span: Span, outcome: str, **fields: Any) -> None:
        span.end_ms = self.now_ms()
        span.outcome = outcome
        for key, value in fields.items():
            setattr(span, key, value)


def _degradation_count(cache: Any) -> int:
    """RedisCache의 누적 강등 수. 인메모리 대역처럼 회계가 없으면 0(강등 개념 없음)."""
    value = getattr(cache, "degradation_count", 0)
    return value if isinstance(value, int) else 0


class TimedCache:
    """캐시를 감싸 get/set 구간을 기록한다. `salt`를 키 앞에 붙여 턴 간 적중을 막는다."""

    def __init__(self, inner: Any, recorder: SpanRecorder, *, salt: str = "") -> None:
        self._inner = inner
        self._recorder = recorder
        self.salt = salt

    async def get(self, key: str) -> str | None:
        span = self._recorder.open("cache_get")
        before = _degradation_count(self._inner)
        try:
            value = await self._inner.get(self.salt + key)
        except BaseException as exc:  # 취소(CancelledError)도 구간을 닫고 다시 올린다.
            self._recorder.close(span, type(exc).__name__)
            raise
        self._recorder.close(
            span, "ok", degraded=_degradation_count(self._inner) > before, hit=value is not None
        )
        return value  # type: ignore[no-any-return]

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        span = self._recorder.open("cache_set")
        before = _degradation_count(self._inner)
        try:
            await self._inner.set(self.salt + key, value, ttl_seconds)
        except BaseException as exc:
            self._recorder.close(span, type(exc).__name__)
            raise
        self._recorder.close(span, "ok", degraded=_degradation_count(self._inner) > before)


class TimedProvider:
    """LLM 프로바이더를 감싸 생성 구간을 기록한다. 그 밖의 속성은 안쪽 프로바이더에 위임한다."""

    def __init__(self, inner: Any, recorder: SpanRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    async def generate(self, prompt: str, system: str, decision: Any, **kwargs: Any) -> Any:
        span = self._recorder.open("provider")
        try:
            result = await self._inner.generate(prompt, system, decision, **kwargs)
        except BaseException as exc:
            self._recorder.close(span, type(exc).__name__, model=_model_of(decision))
            raise
        self._recorder.close(span, "ok", model=_model_of(decision))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _model_of(decision: Any) -> str | None:
    """라우터 결정에서 실제 로컬 모델 ID를 푼다. 풀 수 없으면 None(값을 지어내지 않는다)."""
    try:
        from whymath_backend.l3.router import resolve_model

        return resolve_model(decision.local_family, decision.local_model)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001 — 모델명은 부가 정보다. 실패해도 측정은 계속한다.
        return None


# ──────────────────────────────────────────────────────────────────────────
# 순수 분해·집계 — 테스트가 직접 부른다 (서버·DB·Ollama 불요)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Decomposition:
    """한 턴의 소요를 구간별로 나눈 결과(ms)."""

    elapsed_ms: float
    cache_ms: float  # 캐시 get/set 합(강등 포함)
    cache_degraded_ms: float  # 그중 강등으로 끝난 연산의 합
    provider_ms: float
    other_ms: float  # 턴 소요 − 캐시 − 프로바이더 (0 미만으로 내려가지 않는다)
    cache_ops: int
    provider_calls: int
    inflight_at_cancel: str | None  # 취소로 닫힌 구간의 종류. 없으면 None
    dominant: str  # "cache_wait" | "provider" | "non_llm" | "none"


def decompose_turn(spans: Sequence[Span], elapsed_ms: float) -> Decomposition:
    cache_spans = [s for s in spans if s.kind in ("cache_get", "cache_set")]
    provider_spans = [s for s in spans if s.kind == "provider"]
    cache_ms = sum(s.duration_ms for s in cache_spans)
    cache_degraded_ms = sum(s.duration_ms for s in cache_spans if s.degraded)
    provider_ms = sum(s.duration_ms for s in provider_spans)
    other_ms = max(0.0, elapsed_ms - cache_ms - provider_ms)
    cancelled = [s for s in spans if s.outcome == "CancelledError"]
    shares = {"cache_wait": cache_ms, "provider": provider_ms, "non_llm": other_ms}
    dominant = "none"
    if elapsed_ms > 0:
        name, value = max(shares.items(), key=lambda kv: kv[1])
        if value / elapsed_ms >= DOMINANT_SHARE:
            dominant = name
    return Decomposition(
        elapsed_ms=elapsed_ms,
        cache_ms=cache_ms,
        cache_degraded_ms=cache_degraded_ms,
        provider_ms=provider_ms,
        other_ms=other_ms,
        cache_ops=len(cache_spans),
        provider_calls=len(provider_spans),
        inflight_at_cancel=cancelled[-1].kind if cancelled else None,
        dominant=dominant,
    )


def check_instrument(spans: Sequence[Span], obs_record: Mapping[str, Any] | None) -> str:
    """도구 계측 ↔ OPS-134 레코드 대조. 래퍼가 걸리지 않았으면 `MISMATCH`로 드러난다.

    파이프라인은 LLM 호출마다 `cache.get`을 정확히 한 번 부른다. 그래서 `cache_get` 구간 수는
    정책의 `llm_calls`와 같아야 한다. 레코드가 없으면 대조할 수 없다(`NO_RECORD`).
    """
    if obs_record is None or obs_record.get("llm_calls") is None:
        return "NO_RECORD"
    gets = sum(1 for s in spans if s.kind == "cache_get")
    calls = int(obs_record["llm_calls"])
    return "OK" if gets == calls else f"MISMATCH(cache_get={gets},llm_calls={calls})"


def provider_failure_count(spans: Sequence[Span]) -> int:
    """프로바이더 호출이 **실패로 끝난** 구간 수. 예산 취소(`CancelledError`)는 실패가 아니다.

    정책은 프로바이더 예외를 안전 강등으로 삼켜 턴을 정상 종료시킨다. 그래서 LLM이 죽은 실행도
    턴은 "발화"를 내고, 즉시 실패한 호출 시간이 프로바이더 소요로 집계된다 — 이 수가 0이 아니면
    그 실행의 프로바이더 구간은 LLM 소요가 아니다(2026-10-14 Ollama 없는 환경 스모크 실측).
    """
    return sum(
        1 for s in spans if s.kind == "provider" and s.outcome not in ("ok", "CancelledError")
    )


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}ms"


def cold_overhead_estimate(turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """첫 턴(cold)의 첫 프로바이더 호출이 웜 호출 중앙값보다 얼마나 더 걸렸는지.

    **추정치다**: Ollama의 모델 로드와 첫 추론은 한 호출 안에서 일어나 둘로 쪼갤 수 없다. 웜 기준이
    없으면(웜 호출 0건) 추정하지 않고 None을 돌려준다 — 0으로 위장하지 않는다.
    """
    cold_first: float | None = None
    warm: list[float] = []
    for turn in turns:
        provs = [s for s in turn.get("spans", []) if s.get("kind") == "provider"]
        for i, span in enumerate(provs):
            if span.get("end_ms") is None or span.get("outcome") != "ok":
                continue
            dur = float(span["end_ms"]) - float(span["start_ms"])
            if turn.get("cold") and i == 0 and cold_first is None:
                cold_first = dur
            else:
                warm.append(dur)
    warm_median = _median(warm)
    if cold_first is None or warm_median is None:
        return {"cold_first_ms": cold_first, "warm_median_ms": warm_median, "overhead_ms": None}
    return {
        "cold_first_ms": cold_first,
        "warm_median_ms": warm_median,
        "overhead_ms": max(0.0, cold_first - warm_median),
    }


def budget_exceed_table(
    turns: Sequence[Mapping[str, Any]], run_timeout_s: float
) -> list[dict[str, Any]]:
    """「이 예산이면 몇 %의 턴이 넘는가」. 실행 타임아웃보다 큰 예산은 **검열(censored)** 이다.

    그 실행에서 턴은 `run_timeout_s`에서 잘렸으므로, 그보다 큰 예산의 초과율은 알 수 없다. 낮게
    계산하지 않고 `None`을 돌려준다(검열된 표본을 완전한 표본처럼 쓰지 않는다).
    """
    elapsed = [float(t["elapsed_ms"]) for t in turns if t.get("elapsed_ms") is not None]
    rows: list[dict[str, Any]] = []
    for budget_s in BUDGET_CANDIDATES_S:
        if not elapsed or budget_s > run_timeout_s:
            rows.append({"budget_s": budget_s, "exceed_rate": None, "n": len(elapsed)})
            continue
        exceed = sum(1 for e in elapsed if e > budget_s * 1000.0)
        rows.append({"budget_s": budget_s, "exceed_rate": exceed / len(elapsed), "n": len(elapsed)})
    return rows


@dataclass
class RunSummary:
    run_id: str
    header: dict[str, Any]
    turns: list[dict[str, Any]]
    probe: dict[str, Any] | None
    interrupted: bool
    decomps: list[Decomposition] = field(default_factory=list)


def list_run_ids(path: Path) -> list[str]:
    """기록 파일의 실행 id를 헤더가 처음 나온 순서대로. 읽을 수 없는 줄은 알리고 건너뛰지 않는다."""
    seen: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}:{lineno} JSON 해석 실패({type(exc).__name__})"
                ) from exc
            if rec.get("kind") == "header" and rec.get("run_id") not in seen:
                seen.append(rec["run_id"])
    return seen


def load_run(path: Path, run_id: str) -> RunSummary:
    """JSONL에서 **지정한 run_id 한 실행분만** 읽는다. 읽을 수 없는 줄은 건너뛰지 않고 알린다."""
    header: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = []
    probe: dict[str, Any] | None = None
    has_footer = False
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}:{lineno} JSON 해석 실패({type(exc).__name__})"
                ) from exc
            if rec.get("run_id") != run_id:
                continue
            kind = rec.get("kind")
            if kind == "header":
                header = rec
            elif kind == "cache_probe":
                probe = rec
            elif kind == "turn":
                turns.append(rec)
            elif kind == "footer":
                has_footer = True
    if header is None or not turns:
        raise ValueError(
            f"run_id={run_id}: 헤더 또는 턴 기록이 없다(측정 0건 — 통과가 아니라 실패)"
        )
    summary = RunSummary(
        run_id=run_id, header=header, turns=turns, probe=probe, interrupted=not has_footer
    )
    for turn in turns:
        spans = [
            Span(
                kind=s["kind"],
                start_ms=float(s["start_ms"]),
                end_ms=None if s["end_ms"] is None else float(s["end_ms"]),
                outcome=s["outcome"],
                degraded=bool(s.get("degraded")),
                hit=s.get("hit"),
                model=s.get("model"),
            )
            for s in turn.get("spans", [])
        ]
        summary.decomps.append(decompose_turn(spans, float(turn["elapsed_ms"])))
    return summary


def render_run(summary: RunSummary) -> list[str]:
    """한 실행의 분해 요약을 사람이 읽는 줄로 만든다."""
    h = summary.header
    turns, decomps = summary.turns, summary.decomps
    timeout_s = float(h["timeout_seconds"])
    outcomes: dict[str, int] = {}
    for t in turns:
        label = (t.get("ops134") or {}).get("primary_outcome") or "기록없음"
        outcomes[label] = outcomes.get(label, 0) + 1
    # 채택(`adopted`) 외는 전부 LLM 발화가 학생에게 닿지 않은 턴이다(wh1_shadow.PrimaryOutcome).
    fallback_n = sum(n for label, n in outcomes.items() if label != "adopted")
    prov_errors = sum(int(t.get("provider_errors") or 0) for t in turns)
    lines = [
        f"■ 실행 {summary.run_id} — 조건 {h['condition']} · 예산 {timeout_s:g}초 · "
        f"턴 {len(turns)}건" + (" · ⚠ 중단됨(footer 없음)" if summary.interrupted else ""),
        f"  코드 {h.get('code_head') or '미상'} · 모델 로드 상태(첫 턴 전) "
        f"{h.get('ollama_ps_before')} · 콜드 확인 {h.get('cold_verified')}",
    ]
    if summary.probe:
        p = summary.probe
        lines.append(
            f"  캐시 프로브: get {p['ops']}회 중 강등 {p['degraded']}회 · 연산당 중앙값 "
            f"{_fmt_ms(p.get('median_ms'))} · 최대 {_fmt_ms(p.get('max_ms'))} · "
            f"마지막 예외 {p.get('last_error_type')}"
        )
    elapsed = [d.elapsed_ms for d in decomps]
    lines.append(
        f"  턴 소요: 중앙값 {_fmt_ms(_median(elapsed))} · 최대 {_fmt_ms(max(elapsed))} · "
        f"LLM 발화 미채택 {fallback_n}/{len(turns)}턴 — 결말 {outcomes}"
    )
    if prov_errors:
        lines.append(
            f"  ⚠ 프로바이더 호출 실패 {prov_errors}건 — 이 실행의 프로바이더 구간은 LLM 소요가 "
            "아니다(즉시 실패한 시간). 원인(Ollama 미가동·모델 미설치)을 고치고 다시 측정할 것"
        )
    total = sum(elapsed) or 1.0
    cache = sum(d.cache_ms for d in decomps)
    cache_deg = sum(d.cache_degraded_ms for d in decomps)
    prov = sum(d.provider_ms for d in decomps)
    other = sum(d.other_ms for d in decomps)
    lines.append(
        f"  소요 합 {_fmt_ms(total)} 중 — 캐시 {_fmt_ms(cache)}({cache / total:.0%}, 강등 대기 "
        f"{_fmt_ms(cache_deg)}) · 프로바이더 {_fmt_ms(prov)}({prov / total:.0%}) · "
        f"나머지 {_fmt_ms(other)}({other / total:.0%})"
    )
    calls = [d.provider_calls for d in decomps]
    ops = [d.cache_ops for d in decomps]
    lines.append(
        f"  턴당 프로바이더 호출 중앙값 {_median([float(c) for c in calls])} · 최대 {max(calls)} · "
        f"턴당 캐시 연산 중앙값 {_median([float(o) for o in ops])}"
    )
    dom: dict[str, int] = {}
    for d in decomps:
        dom[d.dominant] = dom.get(d.dominant, 0) + 1
    lines.append(f"  지배 원인(구간이 턴 소요의 {DOMINANT_SHARE:.0%} 이상): {dom}")
    cancel: dict[str, int] = {}
    for d in decomps:
        if d.inflight_at_cancel:
            cancel[d.inflight_at_cancel] = cancel.get(d.inflight_at_cancel, 0) + 1
    if fallback_n or cancel:
        lines.append(f"  취소 시점에 진행 중이던 구간: {cancel or '없음'}")
    checks: dict[str, int] = {}
    for t in turns:
        key = str(t.get("instrument_check", "NO_RECORD")).split("(")[0]
        checks[key] = checks.get(key, 0) + 1
    lines.append(f"  계측 대조(구간 수 ↔ OPS-134 레코드): {checks}")
    cold = cold_overhead_estimate(turns)
    lines.append(
        f"  콜드 로드 추정: 첫 호출 {_fmt_ms(cold['cold_first_ms'])} · 웜 중앙값 "
        f"{_fmt_ms(cold['warm_median_ms'])} · 추가분 {_fmt_ms(cold['overhead_ms'])}"
        + (" (추정 불가: 콜드 턴 또는 웜 표본 없음)" if cold["overhead_ms"] is None else "")
    )
    table = budget_exceed_table(turns, timeout_s)
    cells = [
        f"{r['budget_s']:g}초 "
        + ("검열(알 수 없음)" if r["exceed_rate"] is None else f"{r['exceed_rate']:.0%} 초과")
        for r in table
    ]
    lines.append("  예산별 초과율: " + " · ".join(cells))
    errors = [t for t in turns if t.get("error")]
    if errors:
        kinds: dict[str, int] = {}
        for t in errors:
            kinds[str(t["error"])] = kinds.get(str(t["error"]), 0) + 1
        lines.append(f"  ⚠ 도구 측 오류 턴 {len(errors)}건: {kinds}")
    return lines


# ──────────────────────────────────────────────────────────────────────────
# 기록기
# ──────────────────────────────────────────────────────────────────────────
class JsonlWriter:
    """한 줄 쓸 때마다 flush+fsync — 도중에 멈춰도 그때까지의 증거가 디스크에 있다."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh: Any = None  # 첫 기록 때 연다 — 거부된 실행이 빈 파일을 남기지 않게

    def write(self, record: Mapping[str, Any]) -> None:
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()


class _ObsCapture(logging.Handler):
    """OPS-134 관측 레코드(JSON 한 줄)를 가로챈다. 다른 로거 출력은 건드리지 않는다."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            parsed = json.loads(record.getMessage())
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(parsed, dict):
            self.records.append(parsed)


@contextmanager
def capture_observations() -> Iterator[_ObsCapture]:
    """관측 레코드 로거에 가로채기 핸들러를 달았다가, 나올 때 로거 수준·핸들러를 원상복구한다."""
    capture = _ObsCapture()
    obs_logger = logging.getLogger(_OBS_RECORD_LOGGER)
    prev_level = obs_logger.level
    obs_logger.setLevel(logging.INFO)
    obs_logger.addHandler(capture)
    try:
        yield capture
    finally:
        obs_logger.removeHandler(capture)
        obs_logger.setLevel(prev_level)


# ──────────────────────────────────────────────────────────────────────────
# Ollama·git 보조 호출 (모두 타임아웃)
# ──────────────────────────────────────────────────────────────────────────
def _ollama_loaded_models(host: str) -> list[str] | None:
    """`/api/ps`로 지금 메모리에 올라온 모델 이름. 조회 자체가 실패하면 None(빈 목록과 구별)."""
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/ps", timeout=_HTTP_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return [str(m.get("name")) for m in body.get("models", [])]
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _ollama_unload_all(host: str, models: Iterable[str]) -> None:
    """올라온 모델을 `keep_alive: 0`으로 내린다. 실패는 호출 쪽이 `/api/ps` 재조회로 가린다."""
    for name in models:
        payload = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(
            host.rstrip("/") + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S * 6) as resp:
                resp.read()
        except (urllib.error.URLError, OSError, TimeoutError):
            pass


def _make_cold(host: str) -> tuple[bool, list[str] | None]:
    """모델을 전부 내리고 **실제로 비었는지** 확인한다. (콜드 확인 여부, 내리기 전 목록)."""
    before = _ollama_loaded_models(host)
    if before:
        _ollama_unload_all(host, before)
    for _ in range(10):
        after = _ollama_loaded_models(host)
        if after == []:
            return True, before
        time.sleep(1.0)
    return False, before


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",  # 로케일(cp949) 디코딩 금지 — HARN-19
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# ──────────────────────────────────────────────────────────────────────────
# 측정 본체
# ──────────────────────────────────────────────────────────────────────────
def _host_port(url: str) -> str:
    """자격증명 없이 호스트:포트만. URL 전체는 비밀번호를 담을 수 있어 기록하지 않는다."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.hostname}:{parts.port}"


async def _cache_probe(cache: Any, ops: int) -> dict[str, Any]:
    """실제 캐시 코드 경로로 get을 `ops`회 — 조건 확인과 연산당 비용 측정을 한 번에 한다."""
    durations: list[float] = []
    degraded = 0
    for i in range(ops):
        before = _degradation_count(cache)
        t = time.monotonic()
        await cache.get(f"ops141:probe:{uuid.uuid4().hex}:{i}")
        durations.append((time.monotonic() - t) * 1000.0)
        if _degradation_count(cache) > before:
            degraded += 1
    snap = getattr(cache, "degradation_snapshot", None)
    return {
        "ops": ops,
        "degraded": degraded,
        "median_ms": _median(durations),
        "max_ms": max(durations) if durations else None,
        "last_error_type": snap().last_error_type if callable(snap) else None,
    }


def _condition_matches(condition: str, probe: Mapping[str, Any] | None) -> str | None:
    """선언한 조건이 프로브 결과와 맞으면 None, 아니면 거부 사유. 혼합이면 불안정으로 거부."""
    if condition == "memory":
        return None
    if probe is None or probe["ops"] < 1:
        return "캐시 프로브가 0회라 조건을 확인할 수 없다(--cache-probe-ops는 1 이상)"
    if probe["degraded"] == probe["ops"]:
        return (
            None
            if condition == "redis-down"
            else "redis-up을 선언했지만 Redis가 응답하지 않는다(프로브 전부 강등)"
        )
    if probe["degraded"] == 0:
        return (
            None
            if condition == "redis-up"
            else "redis-down을 선언했지만 Redis가 응답한다 — 그 포트를 점유한 프로세스를 확인할 것"
        )
    return (
        f"Redis 응답이 불안정하다(프로브 {probe['ops']}회 중 강등 {probe['degraded']}회)"
        " — 조건 불성립"
    )


async def _run_turn(
    *,
    provider: Any,
    cache: TimedCache,
    recorder: SpanRecorder,
    capture: _ObsCapture,
    scenario: tuple[str, str, tuple[str, ...]],
    run_id: str,
    seq: int,
    rep: int,
    cold: bool,
    timeout_s: float,
) -> dict[str, Any]:
    from whymath_backend.harness.wh1_primary import run_wh1_primary_turn

    label, student, steps = scenario
    recorder.start_turn()
    cache.salt = f"ops141:{run_id}:{seq}:"
    capture.records.clear()
    started = time.monotonic()
    error: str | None = None
    returned = False
    try:
        utterance = await asyncio.wait_for(
            run_wh1_primary_turn(
                student_solution=student,
                solution_steps=list(steps),
                active_hypotheses=[],
                provider=provider,
                cache=cache,
                trace=None,
                turn_index=1,
                dialogue_id=f"ops141-{run_id}",
                timeout_seconds=timeout_s,
            ),
            timeout=timeout_s + _TURN_WALL_MARGIN_S,
        )
        returned = utterance is not None
    except Exception as exc:  # noqa: BLE001 — 도구 측 오류도 한 줄로 남기고 다음 턴으로 간다.
        error = type(exc).__name__
    elapsed_ms = (time.monotonic() - started) * 1000.0
    obs = capture.records[-1] if capture.records else None
    spans = list(recorder.spans)
    return {
        "kind": "turn",
        "run_id": run_id,
        "seq": seq,
        "rep": rep,
        "scenario": label,
        "cold": cold,
        "timeout_seconds": timeout_s,
        "elapsed_ms": round(elapsed_ms, 1),
        "returned_utterance": returned,
        "error": error,
        "spans": [s.to_dict() for s in spans],
        "ops134": (
            None
            if obs is None
            else {
                k: obs.get(k)
                for k in (
                    "primary_outcome",
                    "elapsed_ms",
                    "llm_calls",
                    "llm_calls_finished",
                    "llm_ms_total",
                )
            }
        ),
        "provider_errors": provider_failure_count(spans),
        "instrument_check": check_instrument(spans, obs),
    }


async def _measure(args: argparse.Namespace, writer: JsonlWriter, run_id: str) -> int:
    from whymath_backend.config import get_settings
    from whymath_backend.l3.cache.redis_cache import RedisCache
    from whymath_backend.l3.interfaces import InMemoryCache
    from whymath_backend.l3.providers.ollama import OllamaProvider

    settings = get_settings()
    timeout_s = (
        float(args.timeout_seconds)
        if args.timeout_seconds
        else settings.wh1_primary_timeout_seconds
    )

    inner_cache: Any
    redis_target: str | None = None
    if args.condition == "memory":
        inner_cache = InMemoryCache()
    else:
        url = args.redis_url or settings.redis_url
        redis_target = _host_port(url)
        inner_cache = RedisCache(settings=settings.model_copy(update={"redis_url": url}))

    probe = None
    if args.condition != "memory":
        probe = await _cache_probe(inner_cache, args.cache_probe_ops)
    refusal = _condition_matches(args.condition, probe)
    if refusal is not None:
        print(f"[거부] {refusal} — 아무것도 측정하지 않았다.", file=sys.stderr)
        return 2

    ollama_host = settings.ollama_host
    if _ollama_loaded_models(ollama_host) is None:
        print(
            f"[거부] Ollama({ollama_host})가 응답하지 않는다 — 프로바이더가 즉시 실패해 "
            "소요 분해가 무의미하다. 아무것도 측정하지 않았다.",
            file=sys.stderr,
        )
        return 2
    cold_verified: bool | None = None
    if args.cold:
        cold_verified, ps_before = _make_cold(ollama_host)
        if not cold_verified:
            print(
                "[거부] --cold를 요청했지만 모델을 메모리에서 내린 것이 확인되지 않았다.",
                file=sys.stderr,
            )
            return 2
    else:
        ps_before = _ollama_loaded_models(ollama_host)

    writer.write(
        {
            "kind": "header",
            "run_id": run_id,
            "tool_version": TOOL_VERSION,
            "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "condition": args.condition,
            "timeout_seconds": timeout_s,
            "reps": args.reps,
            "cold_requested": bool(args.cold),
            "cold_verified": cold_verified,
            "ollama_ps_before": ps_before,
            "redis_target": redis_target,
            "code_head": _git_head(),
            "python": sys.version.split()[0],
        }
    )
    if probe is not None:
        writer.write({"kind": "cache_probe", "run_id": run_id, **probe})

    recorder = SpanRecorder()
    cache = TimedCache(inner_cache, recorder)
    provider = TimedProvider(OllamaProvider(), recorder)
    seq = 0
    interrupted = False
    failures = 0
    try:
        with capture_observations() as capture:
            for rep in range(1, args.reps + 1):
                for scenario in SCENARIOS:
                    seq += 1
                    rec = await _run_turn(
                        provider=provider,
                        cache=cache,
                        recorder=recorder,
                        capture=capture,
                        scenario=scenario,
                        run_id=run_id,
                        seq=seq,
                        rep=rep,
                        cold=bool(cold_verified) and seq == 1,
                        timeout_s=timeout_s,
                    )
                    writer.write(rec)
                    failures += 1 if (rec["error"] or rec["provider_errors"]) else 0
                    outcome = (rec["ops134"] or {}).get("primary_outcome") or "기록없음"
                    print(
                        f"  턴 {seq:>2} {scenario[0]:<14} {rec['elapsed_ms']:>9,.0f}ms "
                        f"결말={outcome} 대조={rec['instrument_check']}"
                        + (
                            f" 프로바이더실패={rec['provider_errors']}"
                            if rec["provider_errors"]
                            else ""
                        )
                        + (f" 오류={rec['error']}" if rec["error"] else ""),
                        flush=True,
                    )
    except KeyboardInterrupt:
        interrupted = True
    finally:
        writer.write(
            {"kind": "footer", "run_id": run_id, "turns_done": seq, "interrupted": interrupted}
        )
    return 1 if (interrupted or failures) else 0


def _cmd_measure(args: argparse.Namespace) -> int:
    if args.reps < 1:
        print("[거부] --reps는 1 이상.", file=sys.stderr)
        return 2
    run_id = args.run_id or (
        f"{args.condition}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    )
    out = Path(args.out)
    writer = JsonlWriter(out / _RECORD_FILE)
    print(f"RUN_ID={run_id}", flush=True)
    try:
        return asyncio.run(_measure(args, writer, run_id))
    finally:
        writer.close()


def _cmd_summarize(args: argparse.Namespace) -> int:
    path = Path(args.out) / _RECORD_FILE
    if not path.is_file():
        print(f"[측정 실패] 기록 파일이 없다: {path}", file=sys.stderr)
        return 1
    if args.all_in_file == bool(args.run_id):
        print("[인자 오류] --run-id 또는 --all-in-file 중 정확히 하나를 줄 것.", file=sys.stderr)
        return 2
    try:
        run_ids = list_run_ids(path) if args.all_in_file else args.run_id
    except ValueError as exc:
        print(f"[측정 실패] {exc}", file=sys.stderr)
        return 1
    if not run_ids:
        print(f"[측정 실패] 기록 파일에 실행(header)이 하나도 없다: {path}", file=sys.stderr)
        return 1
    status = 0
    for run_id in run_ids:
        try:
            summary = load_run(path, run_id)
        except ValueError as exc:
            print(f"[측정 실패] {exc}", file=sys.stderr)
            status = 1
            continue
        print("\n".join(render_run(summary)))
        print()
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="한 조건으로 합성 턴을 돌려 구간을 기록한다")
    m.add_argument("--condition", choices=CONDITIONS, required=True)
    m.add_argument("--out", required=True, help="결과 폴더(decompose.jsonl에 이어 쓴다)")
    m.add_argument(
        "--reps", type=int, default=3, help="시나리오 4종을 몇 바퀴 돌릴지(기본 3 = 12턴)"
    )
    m.add_argument(
        "--timeout-seconds", type=float, default=0.0, help="턴 예산(초). 0이면 설정 기본값(15초)"
    )
    m.add_argument("--cold", action="store_true", help="시작 전 Ollama 모델을 내리고 확인한다")
    m.add_argument("--redis-url", default="", help="비우면 설정의 redis_url")
    m.add_argument("--cache-probe-ops", type=int, default=6, help="조건 확인용 get 횟수")
    m.add_argument("--run-id", default="", help="비우면 조건+UTC시각+난수")
    m.set_defaults(func=_cmd_measure)
    s = sub.add_parser("summarize", help="지정한 실행분만 집계해 분해 요약을 낸다")
    s.add_argument("--out", required=True)
    s.add_argument("--run-id", action="append", default=[], help="반복 지정 가능")
    s.add_argument(
        "--all-in-file",
        action="store_true",
        help="이 폴더의 실행을 헤더 등장 순서대로 전부 집계(새로 만든 폴더 전용)",
    )
    s.set_defaults(func=_cmd_summarize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
