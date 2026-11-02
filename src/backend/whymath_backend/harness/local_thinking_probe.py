"""로컬 좌석 사고 모드 켬/끔 실측 비교 — 같은 스펙 표본으로 수락률·지연·출력 토큰 (EOS-203).

왜 필요한가
----------
EOS-197 A6 회차에서 로컬 좌석(`qwen3:30b-a3b`)은 45회 시도 중 3건만 수락됐다. 사고 모드가 출력
4,400~8,100토큰을 내 컨텍스트 8,192와 요청 타임아웃을 넘긴 것이 원인으로 보였다. 저작 CLI에 사고
모드 지시(`--thinking off` → `/no_think`)를 두었지만, **기본값은 실측 없이 바꾸지
않는다**(acceptance
②). 이 도구가 그 실측을 한다 — 같은 스펙 계획 파일을 모드별로 **번갈아** 돌려 수용 게이트 판정까지
낸다. 같은 표본으로 EOS-205의 수정 후 수치(동어반복 거부 = `TautologicalConditionError`)도 나온다.

실제 회차와 같은 경로
-------------------
생성기는 저작 CLI의 조립 함수(`problem_corpus_accumulate._build_live_generator`)로 만든다 — 오개념
카탈로그 주입·과목 선택(`authoring_subject_for_codes`)·`--authoring-tier quality`·`--avoid-recent`가
실제 회차와 같다. 회차 안 구조 중복은 모드별 `signature_index`로 거른다(같은 모드 안에서 같은 구조를
또 내면 `rejected_duplicate` — 실제 회차와 같다). 시드 코퍼스와의 대조는 하지 않는다(두 모드에 같은
조건이라 비교에는 영향이 없고, 시드 파일은 사람 PC 경로라 이 도구의 입력을 늘리지 않는다).

측정 도구 규칙(CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지")
----------------------------------------------------------------
① **실패해도 증거가 남는다** — 시도 1건마다 JSONL 한 줄을 즉시 쓰고 flush한다.
② **실패 원인이 남는다** — 생성 실패는 GenerationLog `error_detail`(타입명 + 안전 요약), 게이트
   거부·검수 필요는 게이트 사유(`outcome.reasons` 앞 3개), 탐침 자신의 예외는 타입명을 행에 싣는다.
③ **이번 실행 것인가** — 모든 행에 `run_id`·시각을 싣고, 요약은 이번 `run_id` 행만 센다.
④ **변별력** — 시작 전에 각 모드의 라우팅 결정과 붙을 지시어를 출력하고, `off` 모드에 지시어가 붙지
   않는 결정이면 **측정을 거부**한다. Ollama 요청 타임아웃이 180초 미만이면 거부한다(30초면 사고
   모드 쪽이 타임아웃으로만 실패해 끔이 유리하게 나온다). 지시어가 **효과가 있었는지**는 요약의
   `off_to_default_token_ratio`(끔/기본 출력 토큰 중앙값)로 본다 — 1에 가까우면 소프트 스위치가 먹지
   않은 것이다(그때는 Ollama `think` API 인자로 바꾸는 후속이 필요하다).

지연은 **벽시계 시간(`wall_s`)** 으로 잰다 — 타임아웃·예외로 usage가 없는 시도까지 포함해야 느린
모드가 살아남은 시도만으로 빨라 보이지 않는다. 모드 순서는 시도마다 돌려(첫 호출의 모델 적재가 한
모드에만 붙지 않게) 편향을 줄인다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.router import thinking_soft_switch
from whymath_backend.schema.provenance import GenerationLog

__all__ = [
    "MIN_TIMEOUT_S",
    "MODES",
    "main",
    "preflight",
    "run_probe",
    "summarize",
]

# 비교 모드 — 이름 → 생성기 `thinking` 값. `default`는 미지정(종전 동작) 대조군이다.
MODES: dict[str, bool | None] = {"default": None, "off": False, "on": True}
# 사고 모드 출력(4,400~8,100토큰)이 끝나기에 충분한 타임아웃 하한 — 런북 [F]·회차 설정과 같은 값.
MIN_TIMEOUT_S = 180.0
# 게이트 사유는 앞 몇 개만 싣는다(행 크기 상한 — 사유 문자열은 우리 게이트가 만든 고정 문구다).
_MAX_REASONS = 3
_MAX_REASON_CHARS = 200

PlanEntry = tuple[str, EquivalenceSpec, str]
GeneratorFactory = Callable[
    [EquivalenceSpec, str, bool | None, Callable[[GenerationLog], None]], object
]


def _failure_kind(detail: str | None) -> str | None:
    """`후보 조립 실패: TautologicalConditionError` → `TautologicalConditionError` 꼴의 사유 축."""
    if not detail:
        return None
    head, _, tail = detail.partition(": ")
    return tail.split("(")[0].strip() or head


def _rotated(modes: Sequence[str], attempt: int) -> list[str]:
    shift = attempt % len(modes)
    return list(modes[shift:]) + list(modes[:shift])


def run_probe(
    plan: Sequence[PlanEntry],
    *,
    modes: Sequence[str],
    per_spec: int,
    factory: GeneratorFactory,
    out: TextIO,
    run_id: str,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict[str, object]]:
    """스펙마다 `per_spec`회 × 모드를 번갈아(순서는 시도마다 회전) 돌린다. 행은 쓸 때마다 flush."""
    rows: list[dict[str, object]] = []
    signatures: dict[str, set[str]] = {mode: set() for mode in modes}  # 모드별 회차 내 구조 중복
    for spec_id, spec, topic_hint in plan:
        logs: dict[str, list[GenerationLog]] = {mode: [] for mode in modes}
        generators = {
            mode: factory(spec, topic_hint, MODES[mode], logs[mode].append) for mode in modes
        }
        for attempt in range(per_spec):
            for mode in _rotated(modes, attempt):
                before = len(logs[mode])
                started = clock()
                row: dict[str, object] = {
                    "run_id": run_id,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "spec_id": spec_id,
                    "mode": mode,
                    "attempt": attempt,
                }
                try:
                    outcome = run_equivalent_generation(
                        spec,
                        generators[mode],  # type: ignore[arg-type]
                        signature_index=signatures[mode],
                    )
                    row["status"] = outcome.status
                    row["reasons"] = [r[:_MAX_REASON_CHARS] for r in outcome.reasons[:_MAX_REASONS]]
                except Exception as exc:  # noqa: BLE001 — 한 시도의 장애가 측정 전체를 죽이지 않게
                    row["status"] = "probe_error"
                    row["probe_error"] = type(exc).__name__
                row["wall_s"] = round(clock() - started, 2)
                new_logs = logs[mode][before:]
                last = new_logs[-1] if new_logs else None
                row["calls"] = len(new_logs)
                row["output_tokens"] = last.output_tokens if last else None
                row["error_detail"] = last.error_detail if last else None
                row["failure_kind"] = _failure_kind(last.error_detail if last else None)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                rows.append(row)
    return rows


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def summarize(rows: Sequence[Mapping[str, object]], run_id: str) -> dict[str, object]:
    """이번 `run_id` 행만 모드별로 센다(규칙 ③). 수락 = 수용 게이트 통과(`accepted`)."""
    by_mode: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        if row.get("run_id") == run_id:
            by_mode.setdefault(str(row["mode"]), []).append(row)
    modes: dict[str, dict[str, object]] = {}
    for mode, items in by_mode.items():
        statuses = Counter(str(r["status"]) for r in items)
        accepted = statuses.get("accepted", 0) + statuses.get("accepted_stored", 0)
        tokens = [float(t) for r in items if isinstance((t := r.get("output_tokens")), int)]
        wall = [float(w) for r in items if isinstance((w := r.get("wall_s")), (int, float))]
        modes[mode] = {
            "attempts": len(items),
            "accepted": accepted,
            "acceptance_rate": round(accepted / len(items), 4) if items else None,
            "statuses": dict(sorted(statuses.items())),
            "failure_kinds": dict(
                sorted(Counter(str(r["failure_kind"]) for r in items if r["failure_kind"]).items())
            ),
            # 지연은 벽시계 — 타임아웃으로 usage가 없는 시도까지 포함한다(규칙 ④ 해설).
            "median_wall_s": _median(wall),
            "max_wall_s": max(wall) if wall else None,
            # 토큰은 usage가 있는 시도만이다 — 그 수를 함께 적어 표본이 줄었음을 숨기지 않는다.
            "median_output_tokens": _median(tokens),
            "token_samples": len(tokens),
        }
    summary: dict[str, object] = {"run_id": run_id, "modes": modes}
    off, base = modes.get("off"), modes.get("default")
    if off and base and off["median_output_tokens"] and base["median_output_tokens"]:
        ratio = float(str(off["median_output_tokens"])) / float(str(base["median_output_tokens"]))
        summary["off_to_default_token_ratio"] = round(ratio, 3)
    return summary


def _live_factory(avoid_recent: int) -> GeneratorFactory:
    """실제 저작 CLI와 같은 조립 — 카탈로그·과목 선택·QUALITY 티어·회피 목록."""

    def build(
        spec: EquivalenceSpec,
        topic_hint: str,
        thinking: bool | None,
        sink: Callable[[GenerationLog], None],
    ) -> object:
        from whymath_backend.harness.problem_corpus_accumulate import (
            _build_live_generator,
            authoring_subject_for_codes,
        )

        subject, slug_prefix = authoring_subject_for_codes(spec.achievement_standard_codes)
        return _build_live_generator(
            topic_hint,
            generation_log_sink=sink,
            authoring_tier="quality",
            avoid_recent=avoid_recent,
            subject=subject,
            slug_prefix=slug_prefix,
            thinking=thinking,
        )

    return build


def preflight(
    plan: Sequence[PlanEntry], modes: Sequence[str], factory: GeneratorFactory
) -> list[str]:
    """각 모드의 라우팅 결정·붙을 지시어를 보고, 변별력이 없으면 거부 사유를 돌려준다(규칙 ④)."""
    problems: list[str] = []
    _, spec, topic_hint = plan[0]
    for mode in modes:
        generator = factory(spec, topic_hint, MODES[mode], lambda _log: None)
        decide = getattr(generator, "_decide_routing", None)
        if not callable(decide):
            problems.append(f"{mode}: 생성기가 라우팅 결정을 내놓지 않는다(_decide_routing 없음)")
            continue
        decision = decide(spec)
        wanted = MODES[mode]
        switch = None if wanted is None else thinking_soft_switch(decision, enabled=wanted)
        print(
            f"PREFLIGHT mode={mode} cost_tier={decision.cost_tier} "
            f"local_model={decision.local_model} switch={switch}"
        )
        if wanted is not None and switch is None:
            problems.append(f"{mode}: 이 결정에는 사고 모드 지시어가 붙지 않는다(비대상 모델)")
    return problems


def _timeout_s() -> float:
    from whymath_backend.config import get_settings

    return float(get_settings().ollama_request_timeout_s)


def main(
    argv: Sequence[str] | None = None,
    *,
    factory: GeneratorFactory | None = None,
    timeout_s: Callable[[], float] = _timeout_s,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--plan", required=True, type=Path, help="스펙 계획 JSONL(저작 CLI와 같다)")
    parser.add_argument("--per-spec", type=int, default=3, help="스펙·모드당 시도 수(기본 3)")
    parser.add_argument("--modes", default="default,off", help="쉼표 구분(default·off·on)")
    parser.add_argument("--avoid-recent", type=int, default=10, help="런북 [F]와 같은 10")
    parser.add_argument("--out", required=True, type=Path, help="시도별 JSONL(이어 쓴다)")
    parser.add_argument("--summary", required=True, type=Path, help="요약 JSON")
    args = parser.parse_args(argv)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if any(m not in MODES for m in modes) or len(set(modes)) < 2 or args.per_spec < 1:
        print(
            f"PROBE_REFUSED=True — modes={modes}(서로 다른 2개 이상·{sorted(MODES)}) "
            f"per_spec={args.per_spec}(1 이상)"
        )
        return 2
    seconds = timeout_s()
    if seconds < MIN_TIMEOUT_S:
        print(
            f"PROBE_REFUSED=True — ollama_request_timeout_s={seconds}(≥{MIN_TIMEOUT_S}이어야 — "
            "WHYMATH_OLLAMA_REQUEST_TIMEOUT_S를 180 이상으로)"
        )
        return 2
    from whymath_backend.harness.problem_corpus_accumulate import load_spec_plan_file

    try:
        # 로더가 빈 계획·형식 오류를 ValueError로 거부한다(fail-loud) — 그 사유를 그대로 낸다.
        plan = load_spec_plan_file(
            args.plan, default_standard_code="", default_difficulty=2.5, default_topic_hint=""
        )
    except (ValueError, OSError) as exc:
        print(f"PROBE_REFUSED=True — 계획을 읽지 못했다({type(exc).__name__}): {exc}")
        return 2
    build = factory or _live_factory(args.avoid_recent)
    problems = preflight(plan, modes, build)
    if problems:
        print("PROBE_REFUSED=True — " + " · ".join(problems))
        return 2
    run_id = uuid.uuid4().hex[:12]
    print(
        f"PROBE_START run_id={run_id} specs={len(plan)} per_spec={args.per_spec} "
        f"modes={','.join(modes)} ollama_timeout_s={seconds}"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        rows = run_probe(
            plan, modes=modes, per_spec=args.per_spec, factory=build, out=handle, run_id=run_id
        )
    summary = summarize(rows, run_id)
    summary["ollama_request_timeout_s"] = seconds
    summary["plan"] = str(args.plan)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    mode_stats = summary["modes"]
    assert isinstance(mode_stats, dict)
    for mode, stats in mode_stats.items():
        print(
            f"PROBE_RESULT mode={mode} accepted={stats['accepted']}/{stats['attempts']} "
            f"rate={stats['acceptance_rate']} median_wall_s={stats['median_wall_s']} "
            f"median_tokens={stats['median_output_tokens']}(n={stats['token_samples']}) "
            f"failures={stats['failure_kinds']}"
        )
    print(f"PROBE_TOKEN_RATIO off/default={summary.get('off_to_default_token_ratio')}")
    print(f"PROBE_DONE=True ROWS={len(rows)} SUMMARY={args.summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    sys.exit(main())
