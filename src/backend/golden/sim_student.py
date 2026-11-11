"""AI 시뮬레이션 학생(S11) — LLM이 오개념 페르소나를 연기해 골든 패스 API를 실제로 호출한다.

튜터 LLM과 학생 LLM이 서로 대화하는 구조다. 학생 쪽은 이 파일만 쓰고, 튜터 쪽(api.py·tutor.py)은
한 줄도 고치지 않는다 — HTTP로만 만난다(httpx.ASGITransport로 golden.api:app을 직접 부른다).

실행: `cd src/backend && python -m golden.sim_student --persona slope-blind --problems 10`

- 닉네임은 `sim-<페르소나>`(재실행이면 `sim-<페르소나>-r2`)뿐이다. 실명·학교·학년은 없다.
- 학생 LLM에는 페르소나 지시 + 문제 본문 + 지금까지의 대화만 보낸다. 닉네임·session_id·정답은 넣지
  않는다. 프롬프트마다 닉네임·session_id가 섞였는지 검사하고, 섞이면 즉시 멈춘다.
- 학생 LLM 호출도 공통 규칙 8번대로 프로바이더 팩토리(build_cloud_provider)를 거친다.
- GOLDEN_FAKE_LLM=1이면 학생 LLM을 부르지 않고 페르소나별 고정 대본(문제당 오답 1회 → 정답)을 쓴다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select

from golden import problems, store
from golden.api import app

# 옛 코드에서 가져온 것: 라우터 결정 + 프로바이더 팩토리(tutor.py와 같은 경로 · HARVEST.md)
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.providers.factory import build_cloud_provider
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType

logger = logging.getLogger(__name__)

# 저장소 루트 — 페르소나 문서와 로그 폴더를 찾는 기준
REPO_ROOT = Path(__file__).resolve().parents[3]
PERSONAS_PATH = REPO_ROOT / "golden" / "sim_personas.md"
LOGS_DIR = REPO_ROOT / "golden" / "logs"

# 페르소나 3종(지시서 S11 — 4종 이상 만들지 않는다)
PERSONAS = ("slope-blind", "sign-slip", "no-setup")

# 한 문제에서 학생이 낼 수 있는 입력 최대 횟수(튜터 3턴 + 마지막 판정 1회)
MAX_ATTEMPTS = 4

# 학생 LLM 1회 호출 제한 시간(초)과 실패 시 재시도 횟수
STUDENT_LLM_TIMEOUT_S = 30.0
STUDENT_LLM_TRIES = 2

# 가짜 모드 대본의 오답 1줄(숫자를 넣지 않는다 — 우연히 정답이 되지 않게)
FAKE_WRONG_LINE = {
    "slope-blind": "y끼리 빼면 되는 거 아니에요?",
    "sign-slip": "음수 곱하면 양수 아니에요?",
    "no-setup": "그냥 아무 숫자나 쓰면 돼요?",
}

# turns CSV 열 — S9(본인 출처) 추출 SQL과 같은 열·같은 순서(닉네임·session_id 제외)
CSV_COLUMNS = (
    "id",
    "problem_id",
    "turn_no",
    "kind",
    "correct",
    "student_text",
    "tutor_text",
    "created_at",
)


class SimStudentError(RuntimeError):
    """시뮬레이션을 이어 갈 수 없는 상태(학생 LLM 연속 실패·개인정보 혼입·계약 위반)."""


@dataclass
class ProblemLog:
    """문제 1개의 시뮬레이션 결과."""

    problem_id: str
    student_lines: list[str] = field(default_factory=list)
    tutor_lines: list[str] = field(default_factory=list)
    attempts: int = 0
    turns_used: int = 0
    correct: bool | None = None
    degraded_tutor_turns: int = 0


@dataclass
class SimResult:
    """실행 1회의 결과. prompts는 학생 LLM에 보낸(또는 가짜 모드에서 만든) 프롬프트 전부다."""

    persona: str
    nickname: str
    session_id: str
    mode: str
    retry_rule: bool
    problems: list[ProblemLog] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    student_llm_calls: int = 0
    student_llm_failures: int = 0
    final_mastery: float = 0.0
    elapsed_s: float = 0.0
    error: str | None = None


def _fake_mode() -> bool:
    """GOLDEN_FAKE_LLM=1이면 가짜 모드(튜터와 같은 환경변수 · 호출 시점에 읽는다)."""
    return os.environ.get("GOLDEN_FAKE_LLM") == "1"


def _sections(markdown: str) -> dict[str, str]:
    """`## 제목` 절마다 본문(빈 줄·`>` 메모 줄 제외)을 한 문단으로 모은다."""
    result: dict[str, str] = {}
    current: str | None = None
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            result[current] = ""
            continue
        if current is None or not line or line.startswith(">"):
            continue
        result[current] = (result[current] + " " + line).strip()
    return result


def load_persona_system(persona: str, *, retry_rule: bool = False) -> str:
    """sim_personas.md에서 학생 LLM의 시스템 프롬프트를 만든다.

    구성: 공통 말투 + 페르소나 (+ 재실행 지시).
    """
    if persona not in PERSONAS:
        raise SimStudentError(f"알 수 없는 페르소나: {persona}")
    sections = _sections(PERSONAS_PATH.read_text(encoding="utf-8"))
    parts = [sections["공통 말투"], sections[persona]]
    if retry_rule:
        parts.append(sections["재실행 추가 지시"])
    return "\n".join(parts)


def build_student_prompt(stem: str, log: ProblemLog) -> str:
    """학생 LLM의 사용자 프롬프트 — 문제 본문 + 이번 문제에서 오간 말만 담는다(정답·식별자 없음)."""
    lines = [f"문제: {stem}", "지금까지 대화:"]
    if not log.student_lines:
        lines.append("(아직 없음)")
    for i, said in enumerate(log.student_lines):
        lines.append(f"나: {said}")
        if i < len(log.tutor_lines):
            lines.append(f"튜터: {log.tutor_lines[i]}")
    lines.append("이어서 네가 입력창에 칠 다음 한 줄만 써라.")
    return "\n".join(lines)


def _clean_line(text: str) -> str:
    """LLM 출력에서 첫 줄만 남기고 '나:'·'학생:' 머리말과 따옴표를 뗀다."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    for prefix in ("나:", "학생:", "나 :", "학생 :"):
        if line.startswith(prefix):
            line = line[len(prefix) :].strip()
    return line.strip("\"'“”‘’").strip()


def _routing_request() -> RoutingRequest:
    """학생 LLM 1회의 라우팅 요청 — tutor.py와 같은 신호로 CLOUD_MID 결정을 받는다.

    입력은 자체 생성 문항(WHYMATH_GENERATED) 본문과 시뮬레이션 대화뿐이라 반출 가능 등급이다.
    """
    return RoutingRequest(
        task_type="coach",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=100.0,
        conversation_phase="probing",
        data_licenses=(LicenseType.WHYMATH_GENERATED,),
    )


async def _live_student_line(system: str, prompt: str, result: SimResult) -> str:
    """실제 학생 LLM을 불러 다음 입력 1줄을 받는다. 실패는 타입명을 남기고 1회 재시도한다."""
    last_error = "없음"
    for _ in range(STUDENT_LLM_TRIES):
        result.student_llm_calls += 1
        try:
            decision = Router().route(_routing_request())
            provider = build_cloud_provider()
            generated = await asyncio.wait_for(
                provider.generate(prompt, system, decision), timeout=STUDENT_LLM_TIMEOUT_S
            )
            line = _clean_line(generated.text)
            if not line:
                raise ValueError("학생 LLM 응답이 빈 문자열이다")
            return line
        except Exception as exc:  # noqa: BLE001 — 재시도 후에도 실패하면 아래에서 멈춘다
            result.student_llm_failures += 1
            last_error = type(exc).__name__
            logger.warning("sim 학생 LLM 호출 실패: %s", last_error)
    raise SimStudentError(f"학생 LLM이 {STUDENT_LLM_TRIES}회 연속 실패했다: {last_error}")


def _fake_student_line(persona: str, problem_id: str, attempt: int) -> str:
    """가짜 모드 대본 — 첫 입력은 페르소나별 오답 1줄, 두 번째부터는 정답(문항 파일에서 읽는다)."""
    if attempt == 1:
        return FAKE_WRONG_LINE[persona]
    answer = next(p["answer"] for p in problems.load_problems() if p["id"] == problem_id)
    return answer


def _check_privacy(prompt: str, nickname: str, session_id: str) -> None:
    """학생 LLM 입력에 닉네임·session_id가 섞이면 즉시 멈춘다(공통 규칙 9)."""
    if nickname in prompt or session_id in prompt:
        raise SimStudentError("학생 LLM 프롬프트에 닉네임 또는 session_id가 들어갔다")


async def run_simulation(
    persona: str,
    n_problems: int,
    *,
    retry_rule: bool = False,
    nickname: str | None = None,
) -> SimResult:
    """페르소나 1종으로 문제 n개를 끝까지 푼다. 문제마다 graded가 올 때까지(최대 4회) 입력한다."""
    nick = nickname or (f"sim-{persona}-r2" if retry_rule else f"sim-{persona}")
    if not nick.startswith("sim-"):
        raise SimStudentError("시뮬레이션 닉네임은 sim-* 이어야 한다")
    system = load_persona_system(persona, retry_rule=retry_rule)
    fake = _fake_mode()
    started = time.monotonic()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://golden") as client:
        r = await client.post("/golden/session", json={"nickname": nick})
        r.raise_for_status()
        session_id = str(r.json()["session_id"])
        result = SimResult(
            persona=persona,
            nickname=nick,
            session_id=session_id,
            mode="fake" if fake else "live",
            retry_rule=retry_rule,
        )

        try:
            await _solve_problems(client, result, system, n_problems)
        except SimStudentError as exc:
            # 멈춰도 결과(쌓인 턴·오류 사유)는 돌려준다 — 호출자가 CSV로 남긴다
            result.error = str(exc)

    result.elapsed_s = round(time.monotonic() - started, 1)
    return result


async def _solve_problems(
    client: httpx.AsyncClient, result: SimResult, system: str, n_problems: int
) -> None:
    """문제 n개를 차례로 푼다. 문제마다 graded가 올 때까지(최대 4회) 입력한다."""
    persona, nick, session_id = result.persona, result.nickname, result.session_id
    fake = result.mode == "fake"
    for _ in range(n_problems):
        r = await client.get("/golden/next", params={"session_id": session_id})
        r.raise_for_status()
        problem = r.json()
        log = ProblemLog(problem_id=str(problem["id"]))
        result.problems.append(log)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = build_student_prompt(str(problem["stem"]), log)
            _check_privacy(system + "\n" + prompt, nick, session_id)
            result.prompts.append(system + "\n" + prompt)
            if fake:
                line = _fake_student_line(persona, log.problem_id, attempt)
            else:
                line = await _live_student_line(system, prompt, result)
            log.student_lines.append(line)
            log.attempts = attempt

            r = await client.post(
                "/golden/answer",
                json={"session_id": session_id, "problem_id": log.problem_id, "text": line},
            )
            r.raise_for_status()
            body = r.json()
            if body["kind"] == "graded":
                log.correct = bool(body["correct"])
                log.turns_used = int(body["turns_used"])
                result.final_mastery = float(body["mastery"])
                break
            log.tutor_lines.append(str(body["message"]))
            if body.get("degraded"):
                log.degraded_tutor_turns += 1
        else:
            raise SimStudentError(f"{log.problem_id}: {MAX_ATTEMPTS}회 입력 뒤에도 graded가 없다")


async def fetch_turn_rows(session_id: str) -> list[dict[str, object]]:
    """이 세션의 golden.turns 행을 기록 순서대로 읽는다(닉네임·session_id 열 제외)."""
    columns = [getattr(store.turns.c, name) for name in CSV_COLUMNS]
    query = (
        select(*columns)
        .where(store.turns.c.session_id == uuid.UUID(session_id))
        .order_by(store.turns.c.id)
    )
    async with store._engine().connect() as conn:  # noqa: SLF001 — 골든 패키지 안의 같은 엔진
        rows = (await conn.execute(query)).mappings().all()
    return [dict(row) for row in rows]


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    """turns 행을 UTF-8 CSV로 쓴다(S9 추출과 같은 열)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in CSV_COLUMNS})


def summary_dict(result: SimResult) -> dict[str, object]:
    """요약 JSON — 프롬프트 원문 대신 개수만 남긴다(session_id는 남기지 않는다)."""
    data = asdict(result)
    data.pop("session_id")
    data["prompts_checked"] = len(data.pop("prompts"))
    data["privacy_violations"] = 0  # _check_privacy가 위반 시 실행을 멈추므로 여기까지 오면 0
    return data


async def _main_async(args: argparse.Namespace) -> int:
    """CLI 본체 — 시뮬레이션 → turns CSV·요약 JSON 저장. 중간에 멈춰도 쌓인 턴은 CSV로 남긴다."""
    stem = f"sim_{args.persona}" + ("_r2" if args.retry_rule else "")
    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"{stem}_turns.csv"
    result = await run_simulation(args.persona, args.problems, retry_rule=args.retry_rule)
    rows = await fetch_turn_rows(result.session_id)
    write_csv(rows, csv_path)
    summary = summary_dict(result)
    summary["turn_rows"] = len(rows)
    (out_dir / f"{stem}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    graded = sum(1 for p in result.problems if p.correct is not None)
    print(
        f"SIM_DONE persona={args.persona} mode={result.mode} problems={len(result.problems)} "
        f"graded={graded} correct={sum(1 for p in result.problems if p.correct)} "
        f"turn_rows={len(rows)} student_llm_calls={result.student_llm_calls} "
        f"elapsed_s={result.elapsed_s} csv={csv_path}"
    )
    if result.error is not None:
        print(f"SIM_FAILED: {result.error}", file=sys.stderr)
        return 1
    return 0 if graded == args.problems else 1


def main(argv: list[str] | None = None) -> int:
    """`python -m golden.sim_student --persona <이름> --problems <수>`."""
    parser = argparse.ArgumentParser(description="골든 패스 AI 시뮬레이션 학생(S11)")
    parser.add_argument("--persona", required=True, choices=PERSONAS)
    parser.add_argument("--problems", type=int, default=10)
    parser.add_argument(
        "--retry-rule",
        action="store_true",
        help="'막히면' 규칙 재실행 1회 — 페르소나 지시 뒤에 재실행 추가 지시 1줄을 붙인다",
    )
    parser.add_argument("--out-dir", default=str(LOGS_DIR))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
