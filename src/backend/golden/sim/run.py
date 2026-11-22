"""시뮬레이터 러너(S19 · F-00) — 학생 모델(S18)을 튜터(골든 API)에 붙여 세션을 돌리고 M1~M5를 잰다.

실행(저장소의 src/backend 폴더에서):
    python -m golden.sim.run --sessions 120 --personas P1,P2,P5,P7          # 야간 스모크
    SIM_FULL=1 python -m golden.sim.run --sessions 720        # 주 1회 전체(Kiki 머신)

- 세션 = (페르소나, 문항, 회차) 1개다(30문항 × 페르소나 8 × 3회 = 720).
  공유 계약 jsonl 한 줄이 세션 1개다.
- HTTP로만 밟는다(실학생과 같은 길): 페르소나·회차마다 GP-1 `POST /golden/session`(닉네임
  `sim-<P>-<회차>`) 1번 → 문항마다 GP-2 `GET /golden/next` → 학생 발화 →
  GP-3/4 `POST /golden/answer` … → GP-5/6 graded. `--base-url`이 없으면
  `httpx.ASGITransport`로 `golden.api:app`을 부른다(S11 `sim_student.py`와 같은 방식).
  api.py의 내부 함수는 부르지 않는다.
- 앱 안에서 예외가 나면 실학생처럼 HTTP 500을 받는다(`raise_app_exceptions=False`) — M4가 센다.
- 세션 원자료는 `golden/sim/out/<날짜>/sessions.jsonl`에 **세션마다 즉시** 한 줄씩 쓴다
  (중간에 죽어도 증거가 남게). 세션이 멈춘 원인은 `errors.jsonl`에 바로 쓴다
  (예외 타입명 + 메시지 · 시드 원문 없음).
- `report()`는 `sim_report.json`(가짜 모드면 `sim_report_fake.json`)을 쓰고 차단 기준(M1·M3·M4·M5)을
  하나라도 어기면 exit 1이다. 계약에 없는 보조 숫자(분모·시드 복제 대체 횟수·M1 판정 불가 세션 수)는
  `run_meta.json`에 따로 쓴다 — 계약 파일 모양은 바꾸지 않는다.
- 비용 가드: `--sessions 720`은 환경변수 `SIM_FULL=1`일 때만 — 없으면 120으로 줄이고
  그 사실을 찍는다.
  외부 호출마다 제한 시간(튜터 30초 · 학생 30초). 넘으면 그 세션은 M4(크래시·시간 초과)다.
- 가짜 모드(`GOLDEN_FAKE_LLM=1`)면 튜터·학생 모두 고정 대본이다(CI·테스트 — 실제 LLM 호출 0).

결과가 나빠도 튜터 프롬프트를 고치지 않는다 — 보정(S20) 전의 숫자는 시뮬레이터 버그일 수 있다.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import sys
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import httpx

from golden import problems as problem_bank
from golden.problems import Problem
from golden.sim import errors, metrics, student

logger = logging.getLogger(__name__)

# 저장소 루트 — parents[4] = sim → golden → backend → src → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[4]
OUT_ROOT = REPO_ROOT / "golden" / "sim" / "out"

# 허용 세션 수(공유 계약 — 스모크 120 · 전체 720)와 720을 여는 환경변수
SESSION_CHOICES = (120, 720)
SMOKE_SESSIONS = 120
FULL_SESSIONS = 720
FULL_ENV = "SIM_FULL"

# 외부 호출 1회의 제한 시간(초) — 지시서 S19 비용 가드
TUTOR_TIMEOUT_S = 30.0
STUDENT_TIMEOUT_S = 30.0

# 문항 1개에서 학생이 낼 수 있는 입력 최대 횟수 = 튜터 되묻기 3턴 + 마지막 판정 1회
# (api.MAX_TUTOR_TURNS + 1 — 테스트가 대조한다. 러너는 api를 import하지 않는다: --base-url 모드)
MAX_INPUTS = 4

# 결과 파일 이름(공유 계약) · 보조 파일
SESSIONS_FILE = "sessions.jsonl"
ERRORS_FILE = "errors.jsonl"
META_FILE = "run_meta.json"
REPORT_LIVE = "sim_report.json"
REPORT_FAKE = "sim_report_fake.json"

# 주입기 답을 쓰는 페르소나(P3 = 세션 내내 · P2 = 첫 입력만 — S18 student.reply_async)
INJECTED_PERSONAS = frozenset({"P2", "P3"})

# 러너가 세션 1개를 멈추고 M4로 세는 예외 — 이름 있는 것만 잡는다(조용한 실패 게이트 RS-G2:
# 광범위 except 금지). 여기 없는 예외는 러너 자체의 결함이므로 잡지 않고 실행을 멈춘다.
_SESSION_ERRORS: tuple[type[BaseException], ...] = (
    httpx.HTTPError,  # 연결 실패·읽기 시간 초과 등(--base-url 모드)
    TimeoutError,  # asyncio.wait_for 시간 초과
    student.StudentSimError,  # 학생 모델 실패·프라이버시 위반·시드 없음
    ValueError,  # 응답 JSON이 계약 모양이 아님(json 디코드 포함)
    KeyError,  # 응답 JSON에 계약 필드가 없음
)


class RunnerError(RuntimeError):
    """러너가 세션을 이어 갈 수 없는 상태(HTTP 오류 응답·계약 위반)."""


class HttpStatusError(RunnerError):
    """골든 API가 200이 아닌 응답을 줬다 — 상태 코드를 들고 간다."""

    def __init__(self, status: int, where: str, body: str) -> None:
        super().__init__(f"{where} → HTTP {status}: {body[:200]}")
        self.status = status


_SESSION_ERRORS = _SESSION_ERRORS + (RunnerError,)


@dataclass(frozen=True)
class Plan:
    """실행 계획 — 회차 × 페르소나마다 GP 세션 1개, 그 안에서 문항 `per_round`개."""

    personas: tuple[str, ...]
    rounds: int
    per_round: int

    @property
    def sessions(self) -> int:
        """계획한 세션(=jsonl 줄) 수."""
        return len(self.personas) * self.rounds * self.per_round


def resolve_sessions(requested: int, environ: Mapping[str, str]) -> tuple[int, str | None]:
    """비용 가드 — 720은 SIM_FULL=1일 때만. (실제 세션 수, 줄였으면 그 사유)."""
    if requested == FULL_SESSIONS and environ.get(FULL_ENV) != "1":
        return (
            SMOKE_SESSIONS,
            f"{FULL_ENV}=1이 없어 --sessions {FULL_SESSIONS}을 {SMOKE_SESSIONS}으로 줄였다",
        )
    return requested, None


def make_plan(sessions: int, personas: Sequence[str], n_problems: int) -> Plan:
    """세션 수 → 계획. 회차 = 세션 ÷ (문항 × 페르소나), 1회 미만이면 1회차에 문항을 나눠 쓴다.

    예: 120 · P1,P2,P5,P7 → 1회차 × 30문항 · 120 · 8종 → 1회차 × 15문항 ·
    720 · 8종 → 3회차 × 30문항.
    """
    if not personas:
        raise ValueError("페르소나가 하나도 없다")
    unknown = [p for p in personas if p not in student.PERSONAS]
    if unknown:
        raise ValueError(f"알 수 없는 페르소나: {unknown}")
    k = len(personas)
    rounds = max(1, sessions // (n_problems * k))
    per_round = min(n_problems, sessions // (k * rounds))
    if per_round < 1:
        raise ValueError(f"세션 {sessions}개로는 페르소나 {k}종을 한 번씩도 돌릴 수 없다")
    return Plan(personas=tuple(personas), rounds=rounds, per_round=per_round)


def nickname(persona: str, round_no: int) -> str:
    """시뮬레이션 닉네임(공통 규칙 10) — `sim-<페르소나>-<회차>`."""
    return f"sim-{persona}-{round_no}"


def pick_injection(problem: Problem, persona: str, round_no: int) -> errors.WrongAnswer | None:
    """P2·P3에 줄 주입기 답 — P3는 문항 개념의 오개념 먼저, 그다음은 결정적으로 고른 시작점부터
    처음 맞는 입력(오개념 ID·OP 코드).

    시작점은 (문항, 페르소나, 회차)의 crc32라 회차마다 다른 오개념이 고르게 나오고, 같은 입력이면
    언제나 같은 답이다(M3를 재려면 답이 흔들리면 안 된다). 그 밖의 페르소나는 None.
    """
    if persona not in INJECTED_PERSONAS:
        return None
    if persona == "P3":
        # 오개념 보유형은 문항이 묻는 개념의 오개념을 먼저 쓴다(S20 반복 — 기울기 문항이면 M0568)
        topic = errors.topic_misconception(problem)
        wrong = errors.inject(problem, topic) if topic else None
        if wrong is not None:
            return wrong
    inputs = errors.ALL_INPUTS
    start = zlib.crc32(f"{problem['id']}:{persona}:{round_no}".encode()) % len(inputs)
    for offset in range(len(inputs)):
        wrong = errors.inject(problem, inputs[(start + offset) % len(inputs)])
        if wrong is not None:
            return wrong
    return None


@dataclass
class RunState:
    """실행 1회의 누적 — 세션 줄과 보조 숫자."""

    sessions: list[dict[str, Any]] = field(default_factory=list)
    leak_undecidable: int = 0
    # 튜터가 LLM 실패로 대체 문장을 낸 턴 수(응답의 degraded=True) — 실제 모드에서 이 숫자가 크면
    # M1·M5가 깨끗해도 튜터 LLM을 잰 것이 아니다(대체 문장만 오간 것)
    degraded_tutor_turns: int = 0
    skipped: int = 0
    errors: int = 0


def _json_line(handle: IO[str], record: Mapping[str, Any]) -> None:
    """한 줄 쓰고 바로 디스크로 내보낸다(중간에 죽어도 그 줄까지는 남는다)."""
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


async def _http(call: Any, where: str) -> dict[str, Any]:
    """HTTP 1회 — 튜터 제한 시간 · 200이 아니면 HttpStatusError · JSON dict만 받는다."""
    response: httpx.Response = await asyncio.wait_for(call, timeout=TUTOR_TIMEOUT_S)
    if response.status_code != 200:
        raise HttpStatusError(response.status_code, where, response.text)
    body = response.json()
    if not isinstance(body, dict):
        raise RunnerError(f"{where} 응답이 JSON 객체가 아니다")
    return body


async def _episode(
    client: httpx.AsyncClient,
    persona: str,
    round_no: int,
    session_id: str,
    nick: str,
    bank: Mapping[str, Problem],
    record: dict[str, Any],
    state: RunState,
) -> Problem:
    """문항 1개를 graded까지 푼다. 진행 상황을 `record`에 바로바로 채운다(예외가 나도 남는다)."""
    public = await _http(
        client.get("/golden/next", params={"session_id": session_id}), "GET /golden/next"
    )
    problem = bank[str(public["id"])]
    record["problem_id"] = problem["id"]
    wrong = pick_injection(problem, persona, round_no)
    forced = wrong.text if wrong else None
    record["forced_answer"] = forced
    record["injected_op"] = wrong.op_code if wrong else None
    if persona == "P3" and forced is None:
        raise RunnerError(f"{problem['id']}: 주입기가 P3에 줄 답을 하나도 만들지 못했다")

    history: list[dict[str, str]] = []
    turns: list[dict[str, Any]] = record["turns"]
    for n in range(1, MAX_INPUTS + 1):
        text = await asyncio.wait_for(
            student.reply_async(persona, problem, history, forced, identifiers=(nick, session_id)),
            timeout=STUDENT_TIMEOUT_S,
        )
        body = await _http(
            client.post(
                "/golden/answer",
                json={"session_id": session_id, "problem_id": problem["id"], "text": text},
            ),
            "POST /golden/answer",
        )
        if body["kind"] == "graded":
            turns.append(
                {
                    "n": n,
                    "student": text,
                    "tutor": str(body["feedback"]),
                    "kind": "graded",
                    "correct": bool(body["correct"]),
                }
            )
            return problem
        if body["kind"] != "tutor_turn":
            raise RunnerError(f"{problem['id']}: 알 수 없는 응답 kind={body['kind']!r}")
        message = str(body["message"])
        if body.get("degraded"):
            state.degraded_tutor_turns += 1
        turns.append(
            {"n": n, "student": text, "tutor": message, "kind": "tutor_turn", "correct": False}
        )
        history.append({"student": text, "tutor": message})
    raise RunnerError(
        f"{problem['id']}: {MAX_INPUTS}회 입력 뒤에도 graded가 없다(3턴 강제 이동 깨짐)"
    )


def _finish(record: dict[str, Any], problem: Problem | None, state: RunState) -> None:
    """세션 줄의 판정 필드(leak·render_broken)를 채운다."""
    turns = record["turns"]
    if problem is not None:
        verdict = metrics.session_leak(turns, problem["answer"])
        record["leak"] = verdict is metrics.LeakageVerdict.leaked
        if verdict is metrics.LeakageVerdict.undecidable:
            state.leak_undecidable += 1
    else:
        record["leak"] = False
    record["render_broken"] = metrics.session_render_broken(turns)


async def run_round(
    client: httpx.AsyncClient,
    persona: str,
    round_no: int,
    per_round: int,
    bank: Mapping[str, Problem],
    state: RunState,
    out: IO[str],
    err: IO[str],
) -> None:
    """페르소나 1종 × 회차 1개 — GP 세션 1개를 열고 문항 `per_round`개를 차례로 푼다."""
    nick = nickname(persona, round_no)
    started = time.monotonic()
    try:
        opened = await _http(
            client.post("/golden/session", json={"nickname": nick}), "POST /golden/session"
        )
        session_id = str(opened["session_id"])
    except _SESSION_ERRORS as exc:
        # 세션을 못 열면 이 회차의 세션 전부가 돌지 못한다 — 첫 세션 1줄을 크래시로 남기고
        # 나머지는 미실행으로 센다
        _record_failure(state, out, err, persona, round_no, None, exc, time.monotonic() - started)
        state.skipped += per_round - 1
        return

    for index in range(per_round):
        record: dict[str, Any] = {
            "persona": persona,
            "problem_id": None,
            "turns": [],
            "forced_answer": None,
            "injected_op": None,
            "elapsed_s": 0.0,
            "http_status": 200,
            "leak": False,
            "render_broken": False,
        }
        t0 = time.monotonic()
        problem: Problem | None = None
        try:
            problem = await _episode(
                client, persona, round_no, session_id, nick, bank, record, state
            )
        except _SESSION_ERRORS as exc:
            record["elapsed_s"] = round(time.monotonic() - t0, 3)
            record["http_status"] = exc.status if isinstance(exc, HttpStatusError) else None
            pid = record["problem_id"]
            problem = bank.get(pid) if isinstance(pid, str) else None
            _finish(record, problem, state)
            state.sessions.append(record)
            _json_line(out, record)
            _write_error(state, err, persona, round_no, pid, exc)
            # 판정이 안 났으면 cursor가 그 문항에 멈춰 있다 — 같은 GP 세션으로 이어 가면 같은 문항이
            # 반복되므로 이 회차의 남은 문항은 돌리지 않는다(미실행으로 센다 · 크래시로 세지 않는다)
            state.skipped += per_round - index - 1
            return
        record["elapsed_s"] = round(time.monotonic() - t0, 3)
        _finish(record, problem, state)
        state.sessions.append(record)
        _json_line(out, record)


def _write_error(
    state: RunState,
    err: IO[str],
    persona: str,
    round_no: int,
    problem_id: object,
    exc: BaseException,
) -> None:
    """세션이 멈춘 원인을 바로 남긴다(타입명 + 메시지 앞 300자)."""
    state.errors += 1
    logger.warning(
        "sim 세션 실패 %s 회차%d %s: %s", persona, round_no, problem_id, type(exc).__name__
    )
    _json_line(
        err,
        {
            "persona": persona,
            "round": round_no,
            "problem_id": problem_id,
            "error_type": type(exc).__name__,
            "detail": str(exc)[:300],
        },
    )


def _record_failure(
    state: RunState,
    out: IO[str],
    err: IO[str],
    persona: str,
    round_no: int,
    problem_id: str | None,
    exc: BaseException,
    elapsed: float,
) -> None:
    """GP-1에서 멈춘 회차의 세션 1줄(크래시)."""
    record: dict[str, Any] = {
        "persona": persona,
        "problem_id": problem_id,
        "turns": [],
        "forced_answer": None,
        "injected_op": None,
        "elapsed_s": round(elapsed, 3),
        "http_status": exc.status if isinstance(exc, HttpStatusError) else None,
        "leak": False,
        "render_broken": False,
    }
    state.sessions.append(record)
    _json_line(out, record)
    _write_error(state, err, persona, round_no, problem_id, exc)


def _client(base_url: str | None) -> httpx.AsyncClient:
    """--base-url이 있으면 그 서버, 없으면 ASGI로 golden.api:app(실학생과 같은 HTTP 경로)."""
    timeout = httpx.Timeout(TUTOR_TIMEOUT_S)
    if base_url:
        return httpx.AsyncClient(base_url=base_url, timeout=timeout)
    from golden.api import app  # ASGI 모드에서만 앱을 싣는다(--base-url 모드는 서버를 따로 띄운다)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://golden", timeout=timeout)


async def run(
    plan: Plan,
    out_dir: Path,
    *,
    base_url: str | None = None,
) -> RunState:
    """계획대로 세션을 돌린다. 결과 줄은 `out_dir/sessions.jsonl`에 세션마다 즉시 쓴다."""
    bank = {p["id"]: p for p in problem_bank.load_problems()}
    out_dir.mkdir(parents=True, exist_ok=True)
    # 같은 폴더의 지난 실행 보고서를 먼저 지운다 — 이번 실행이 도중에 죽으면 보고서가 없어야 한다
    # (남아 있으면 지난 실행 숫자가 이번 것처럼 보인다 · S20 2026-11-21 Kiki 머신 실측:
    # 46세션에서 죽은 실행 옆에 앞 실행의 120세션 sim_report.json이 그대로 남았다)
    for stale in (REPORT_LIVE, REPORT_FAKE, META_FILE):
        (out_dir / stale).unlink(missing_ok=True)
    state = RunState()
    with (
        (out_dir / SESSIONS_FILE).open("w", encoding="utf-8") as out,
        (out_dir / ERRORS_FILE).open("w", encoding="utf-8") as err,
    ):
        async with _client(base_url) as client:
            for round_no in range(1, plan.rounds + 1):
                for persona in plan.personas:
                    await run_round(
                        client, persona, round_no, plan.per_round, bank, state, out, err
                    )
    return state


def report(
    state: RunState,
    out_dir: Path,
    *,
    date: str,
    fake: bool,
    plan: Plan,
    notes: Sequence[str] = (),
) -> int:
    """sim_report(_fake).json과 run_meta.json을 쓰고 exit code를 돌려준다(차단 위반 있으면 1)."""
    sessions = state.sessions
    computed = metrics.compute(sessions)
    failures = metrics.blocking_failures(computed)
    exit_code = 1 if failures else 0
    data: dict[str, Any] = {
        "date": date,
        "sessions": len(sessions),
        "mode": "fake" if fake else "live",
        **computed,
        "worst_persona": metrics.worst_persona(sessions),
        "slowest_problem": metrics.slowest_problem(sessions),
        "exit_code": exit_code,
    }
    name = REPORT_FAKE if fake else REPORT_LIVE
    (out_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    meta = {
        "date": date,
        "mode": data["mode"],
        "planned_sessions": plan.sessions,
        "personas": list(plan.personas),
        "rounds": plan.rounds,
        "problems_per_round": plan.per_round,
        "skipped_sessions": state.skipped,
        "error_lines": state.errors,
        "leak_undecidable_sessions": state.leak_undecidable,
        "degraded_tutor_turns": state.degraded_tutor_turns,
        "seed_copy_fallbacks": student.STATS["seed_copy_fallbacks"],
        "blocking_failures": failures,
        "notes": list(notes),
        **{f"count_{k}": v for k, v in metrics.counts(sessions).items()},
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return exit_code


def _summary(state: RunState, out_dir: Path, fake: bool, exit_code: int) -> str:
    """한 줄 요약(로그·런북 자가검증용)."""
    m = metrics.compute(state.sessions)
    return (
        f"SIM_DONE mode={'fake' if fake else 'live'} sessions={len(state.sessions)} "
        f"M1={m['M1']['value']} M2={m['M2']['value']} M3={m['M3']['value']} "
        f"M4={m['M4']['value']} M5={m['M5']['value']} skipped={state.skipped} "
        f"leak_undecidable={state.leak_undecidable} "
        f"degraded_tutor_turns={state.degraded_tutor_turns} "
        f"seed_copy_fallbacks={student.STATS['seed_copy_fallbacks']} "
        f"worst_persona={metrics.worst_persona(state.sessions)} "
        f"slowest_problem={metrics.slowest_problem(state.sessions)} "
        f"exit={exit_code} out={out_dir}"
    )


def _parse_personas(raw: str) -> list[str]:
    """`P1,P2,...` → 목록(공백 무시 · 중복 제거 · 순서 유지)."""
    seen: list[str] = []
    for item in raw.split(","):
        name = item.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """`python -m golden.sim.run --sessions {120|720} --personas P1,... --date YYYY-MM-DD`."""
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="AI 학생 시뮬레이터 러너(S19)")
    parser.add_argument("--sessions", type=int, choices=SESSION_CHOICES, default=SMOKE_SESSIONS)
    parser.add_argument("--personas", default=",".join(student.PERSONAS))
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--base-url", default=None, help="없으면 ASGI로 golden.api:app을 부른다")
    parser.add_argument("--out-dir", default=None, help="기본 golden/sim/out/<날짜>")
    parser.add_argument(
        "--problems",
        type=int,
        default=None,
        help="문항 수 제한(테스트·점검용 · 1회차만 · 기본 30 전부)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    try:
        dt.date.fromisoformat(args.date)
    except ValueError:
        parser.error(f"--date는 YYYY-MM-DD여야 한다: {args.date}")
    sessions, cut_note = resolve_sessions(args.sessions, env)
    notes = [cut_note] if cut_note else []
    if cut_note:
        print(f"SIM_NOTE {cut_note}", file=sys.stderr)
    n_problems = len(problem_bank.load_problems())
    if args.problems is not None:
        if not 1 <= args.problems <= n_problems:
            parser.error(f"--problems는 1~{n_problems}")
        n_problems = args.problems
    personas = _parse_personas(args.personas)
    if args.problems is not None:
        # 점검용 문항 제한은 1회차만 돈다(2문항이 120세션으로 불어나지 않게)
        sessions = min(sessions, len(personas) * n_problems)
    try:
        plan = make_plan(sessions, personas, n_problems)
    except ValueError as exc:
        parser.error(str(exc))
    if plan.sessions != sessions:
        note = (
            f"계획 세션 {plan.sessions}개(요청 {sessions} — 페르소나·문항 수로 나눠떨어지는 만큼)"
        )
        notes.append(note)
        print(f"SIM_NOTE {note}", file=sys.stderr)
    fake = env.get("GOLDEN_FAKE_LLM") == "1"
    out_dir = Path(args.out_dir) if args.out_dir else OUT_ROOT / args.date

    state = asyncio.run(run(plan, out_dir, base_url=args.base_url))
    exit_code = report(state, out_dir, date=args.date, fake=fake, plan=plan, notes=notes)
    print(_summary(state, out_dir, fake, exit_code))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
