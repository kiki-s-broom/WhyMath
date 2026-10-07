"""WH-1 shadow *합성 트래픽* 드라이버 — coach 세션/턴 API에 대표 3모양 풀이를 제출(verdict 유도).

배경 (왜 이 도구가 필요한가)
----------------------------
S1-11 flip 전제 ①("shadow verify verdict 분포 확보")은 shadow가 켜진 서버에 *풀이 단계가
동봉된* coach 트래픽이 실제로 흘러야 채워진다 — `CoachRequest.solution_steps` 동봉 시 WH-1
하네스의 verify 의무(§3.1)가 걸려 verdict가 생성되기 때문이다. 실기기 시연 전후로 그런
트래픽을 손으로 만드는 건 공전 위험(2026-07-16 라이브 측정 공전 선례)이라, 본 모듈이 대표
3모양(방정식 체인·표현식 동치·오전개)을 재현 가능하게 제출한다.

★**합성 트래픽 명시(정직)**: 이 드라이버가 만드는 분포는 *합성*이다 — 실 학생 트래픽의
대표성을 갖는지는 **Kiki(사람)가 판정**한다. 도구는 "verdict 3-state가 각각 유도되는 모양"을
보장할 뿐, 실 분포를 대변한다고 주장하지 않는다.

대표 3모양의 근거 (verify_step 실측 — 2026-07-17)
--------------------------------------------------
- **eq(방정식 변형 체인)**: `2x+3=7 → 2x=4 → x=2`. 등호 포함 단계는 `verify_step`이
  보수적으로 **unverifiable** 처리한다(파싱 불가 → 거짓 incorrect 회피·§3.1) —
  unverifiable-heavy 구간의 대표.
- **expr(표현식 동치)**: `(x+1)(x+2) → x^2+3x+2`(등호 없음). SymPy 심볼릭 동치로
  **correct** — 결정 구간의 대표.
- **bad(오전개 주입)**: expr과 같되 한 스텝을 틀리게(`x^2+4x+2`) — **incorrect** 검출용.
  스텝이 실제로 틀린 수식인지는 테스트가 `verify_step` 실물로 동결한다(가짜 모양 금지).

설계 경계
---------
- **verdict를 자체 집계하지 않는다** — verdict는 서버 shadow 로그가 진실이다. 본 도구의
  출력은 제출 회계(모양별 세션/턴 수·HTTP 오류)뿐이고, 수확은
  `python -m whymath_backend.harness.wh1_shadow_harvest`가 한다(관심사 분리·이중 집계 금지).
- **httpx 동기 클라이언트 주입 가능** — 테스트는 `httpx.MockTransport`로 라이브 0 검증.
- **페이로드는 실 스키마에 유효** — `CoachRequest`/`SessionCreateRequest` 필드만 사용하며
  (extra="forbid"), 테스트가 실물 스키마로 검증해 드리프트를 동결한다. *전 턴*에
  `solution_steps`를 동봉한다(verify 의무 → verdict 생성).
- **never-break 회계**: 요청 1건의 실패(HTTP 비201·네트워크 예외)는 상태코드/예외 타입명별로
  회계하고 다음으로 진행한다 — 예외를 삼킬 때는 타입명을 로그에 남긴다(침묵 실패 금지).

인증: `--token` 미지정 시 시연용 `POST /v1/auth/demo/callback`으로 자동 발급한다 — 서버가
`WHYMATH_DEMO_AUTH_ENABLED=true`로 기동돼 있어야 한다(scripts/demo/run_demo.ps1).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

__all__ = [
    "DEFAULT_MIX",
    "EQUATION_CHAIN_SHAPE",
    "EXPRESSION_EQUIVALENCE_SHAPE",
    "MISEXPANSION_SHAPE",
    "SHAPES",
    "ProbeAuthError",
    "ProbeReport",
    "SessionShape",
    "build_probe_plan",
    "issue_demo_token",
    "main",
    "parse_mix",
    "render_report",
    "run_probe",
]

logger = logging.getLogger(__name__)

_DEMO_STATE_PATH = "/v1/auth/demo/state"
_DEMO_CALLBACK_PATH = "/v1/auth/demo/callback"
_SESSIONS_PATH = "/v1/coach/sessions"

# 종료 코드 — 전 제출 성공 0·오류 존재/인증 실패 2(오류를 성공으로 위장하지 않음).
_EXIT_OK = 0
_EXIT_ERROR = 2

JsonDict = dict[str, object]


def _payload(student_input: str, student_solution: str, steps: list[str]) -> JsonDict:
    """coach 요청 페이로드 1건 — `CoachRequest` 유효 필드만(전 턴 solution_steps 동봉).

    `solution_steps`가 있으면 하네스 verify 의무(§3.1)가 걸려 shadow verdict가 생성된다.
    """
    return {
        "student_input": student_input,
        "student_solution": student_solution,
        "solution_steps": steps,
    }


@dataclass(frozen=True, slots=True)
class SessionShape:
    """대표 트래픽 1모양 — 세션 생성 1 + 턴 append 2(총 3제출·전 턴 solution_steps 동봉)."""

    label: str
    """--mix에서 쓰는 짧은 라벨(eq|expr|bad)."""

    description: str
    """이 모양이 유도하려는 verdict 구간(사람용)."""

    payloads: tuple[JsonDict, ...]
    """제출 페이로드 — [0] 세션 생성, [1:] 턴 append(각각 CoachRequest 유효)."""


# ── 대표 3모양 — verify_step 실측 근거는 모듈 docstring·테스트가 실물로 동결 ──
EQUATION_CHAIN_SHAPE = SessionShape(
    label="eq",
    description="방정식 변형 체인(등호 포함) — 해집합 보존 동치로 correct 구간(S3-02 이후)",
    payloads=(
        _payload(
            "이 방정식 풀이가 맞는지 확인해줘",
            "2x + 3 = 7 이므로 2x = 4, 따라서 x = 2",
            ["2x + 3 = 7", "2x = 4", "x = 2"],
        ),
        _payload(
            "다음 방정식도 풀어봤어",
            "3x - 1 = 8 이므로 3x = 9, 따라서 x = 3",
            ["3x - 1 = 8", "3x = 9", "x = 3"],
        ),
        _payload(
            "마지막 방정식도 확인 부탁해",
            "5x + 2 = 12 이므로 5x = 10, 따라서 x = 2",
            ["5x + 2 = 12", "5x = 10", "x = 2"],
        ),
    ),
)

EXPRESSION_EQUIVALENCE_SHAPE = SessionShape(
    label="expr",
    description="표현식 동치(인수분해형→전개형·등호 없음) — SymPy 결정 구간(correct)",
    payloads=(
        _payload(
            "전개 결과가 맞는지 확인해줘",
            "(x+1)(x+2)를 전개하면 x^2 + 3x + 2",
            ["(x+1)(x+2)", "x^2 + 3x + 2"],
        ),
        _payload(
            "합차공식으로 전개해봤어",
            "(x+3)(x-3)을 전개하면 x^2 - 9",
            ["(x+3)(x-3)", "x^2 - 9"],
        ),
        _payload(
            "분배법칙으로 전개해봤어",
            "2(x + 4)를 전개하면 2x + 8",
            ["2(x + 4)", "2x + 8"],
        ),
    ),
)

MISEXPANSION_SHAPE = SessionShape(
    label="bad",
    description="오전개 주입(expr과 같되 한 스텝이 틀림) — incorrect 검출용",
    payloads=(
        _payload(
            "전개 결과가 맞는지 확인해줘",
            "(x+1)(x+2)를 전개하면 x^2 + 4x + 2",
            ["(x+1)(x+2)", "x^2 + 4x + 2"],  # 오전개 — 실제 전개는 x^2 + 3x + 2
        ),
        _payload(
            "합차공식으로 전개해봤어",
            "(x+3)(x-3)을 전개하면 x^2 - 6",
            ["(x+3)(x-3)", "x^2 - 6"],  # 오전개 — 실제 전개는 x^2 - 9
        ),
        _payload(
            "분배법칙으로 전개해봤어",
            "2(x + 4)를 전개하면 2x + 4",
            ["2(x + 4)", "2x + 4"],  # 분배 누락 — 실제 전개는 2x + 8
        ),
    ),
)

SHAPES: dict[str, SessionShape] = {
    shape.label: shape
    for shape in (EQUATION_CHAIN_SHAPE, EXPRESSION_EQUIVALENCE_SHAPE, MISEXPANSION_SHAPE)
}

# 기본 믹스 — correct 구간(방정식·표현식)을 넉넉히, incorrect 검출용은 소수(2:2:1).
DEFAULT_MIX = "eq:expr:bad=2:2:1"


def parse_mix(spec: str) -> dict[str, int]:
    """`eq:expr:bad=2:2:1` 형식 파싱 — 모양 라벨별 라운드당 세션 수(순수·명시 거부).

    좌변은 콜론 구분 모양 라벨(SHAPES에 있어야 함), 우변은 같은 개수의 음이 아닌 정수.
    전부 0이면 거부한다(빈 측정을 조용히 만들지 않음 — cost_probe rounds<1 거부 동형).
    """
    if spec.count("=") != 1:
        raise ValueError(f"믹스 형식 오류(‘이름:이름=수:수’ 형태여야 함): {spec!r}")
    names_part, counts_part = spec.split("=")
    names = [n.strip() for n in names_part.split(":")]
    counts_raw = [c.strip() for c in counts_part.split(":")]
    if len(names) != len(counts_raw):
        raise ValueError(
            f"믹스 라벨 수({len(names)})와 비율 수({len(counts_raw)}) 불일치: {spec!r}"
        )
    mix: dict[str, int] = {}
    for name, count_raw in zip(names, counts_raw, strict=True):
        if name not in SHAPES:
            raise ValueError(f"알 수 없는 모양 라벨 {name!r} — 사용 가능: {sorted(SHAPES)}")
        if name in mix:
            raise ValueError(f"모양 라벨 중복: {name!r}")
        try:
            count = int(count_raw)
        except ValueError as exc:
            raise ValueError(f"비율이 정수가 아님: {count_raw!r}") from exc
        if count < 0:
            raise ValueError(f"비율은 음수 불가: {count}")
        mix[name] = count
    if sum(mix.values()) == 0:
        raise ValueError("믹스 합이 0 — 제출할 세션이 없다(빈 측정 거부).")
    return mix


def build_probe_plan(mix: dict[str, int], rounds: int) -> list[SessionShape]:
    """믹스를 rounds배로 펼쳐 세션 실행 계획을 만든다(순수 — cost_probe.build_probe_plan 미러)."""
    if rounds < 1:
        raise ValueError("rounds는 1 이상이어야 합니다.")
    unknown = sorted(set(mix) - set(SHAPES))
    if unknown:
        raise ValueError(f"알 수 없는 모양 라벨: {unknown}")
    plan: list[SessionShape] = []
    for _ in range(rounds):
        for label, shape in SHAPES.items():  # 선언 순서 고정(eq→expr→bad·결정론)
            plan.extend([shape] * mix.get(label, 0))
    return plan


class ProbeAuthError(RuntimeError):
    """데모 토큰 자동 발급 실패 — 서버 미도달/플래그 미설정을 명확히 안내(조용한 0건 방지)."""


@dataclass(slots=True)
class ProbeReport:
    """제출 회계 리포트 — verdict는 없다(서버 로그가 진실 — harvest로 수확)."""

    base_url: str
    rounds: int
    mix: dict[str, int]
    sessions_submitted: dict[str, int] = field(default_factory=dict)
    """모양별 세션 생성 성공(201) 수."""
    turns_submitted: dict[str, int] = field(default_factory=dict)
    """모양별 턴 append 성공(201) 수."""
    http_errors: dict[str, int] = field(default_factory=dict)
    """실패 회계 — HTTP 상태코드(문자열)/예외 타입명 → 건수."""
    error_samples: list[str] = field(default_factory=list)
    """실패 표본(최대 5건)."""
    token_auto_issued: bool = False
    """--token 미지정으로 데모 콜백 자동 발급을 썼는지."""

    @property
    def total_errors(self) -> int:
        return sum(self.http_errors.values())


def issue_demo_token(client: httpx.Client) -> str:
    """시연용 데모 콜백으로 JWT 자동 발급 — 실패 시 원인·조치를 담은 ProbeAuthError.

    run_demo.ps1과 **같은 순서**다: `GET /v1/auth/demo/state`로 CSRF state를 먼저 받아
    `POST /v1/auth/demo/callback` 바디에 싣는다(code/redirect_uri는 FakeOAuthProvider가
    무시하는 고정값). SEC-08 이후 콜백은 `state`가 필수라 state 없이 치면 HTTP 422로 첫
    단계에서 죽는다(OPS-111 — 라이브에서 처음 드러났다). 404/비200은 대부분 서버가
    `WHYMATH_DEMO_AUTH_ENABLED=true` 없이 기동된 경우다 — 안내를 오류에 싣는다.
    """
    guidance = (
        "서버가 WHYMATH_DEMO_AUTH_ENABLED=true로 기동됐는지 확인하세요(scripts/demo/run_demo.ps1). "
        "이미 발급된 토큰이 있으면 --token으로 직접 주입할 수 있습니다."
    )
    try:
        state_resp = client.get(_DEMO_STATE_PATH)
    except httpx.HTTPError as exc:
        raise ProbeAuthError(
            f"데모 토큰 발급 실패({type(exc).__name__}) — 서버 미도달. --base-url과 서버 기동"
            "(scripts/demo/run_demo.ps1)을 확인하세요."
        ) from exc
    if state_resp.status_code != 200:
        raise ProbeAuthError(
            f"데모 state 발급 실패(HTTP {state_resp.status_code}) — {guidance}"
        )
    state = state_resp.json().get("state")
    if not isinstance(state, str) or not state:
        raise ProbeAuthError("데모 state 응답에 state가 없음 — 서버 버전을 확인하세요.")
    try:
        resp = client.post(
            _DEMO_CALLBACK_PATH,
            json={"code": "demo", "redirect_uri": "https://demo/cb", "state": state},
        )
    except httpx.HTTPError as exc:
        raise ProbeAuthError(
            f"데모 토큰 발급 실패({type(exc).__name__}) — 서버 미도달. --base-url과 서버 기동"
            "(scripts/demo/run_demo.ps1)을 확인하세요."
        ) from exc
    if resp.status_code != 200:
        raise ProbeAuthError(f"데모 토큰 발급 실패(HTTP {resp.status_code}) — {guidance}")
    token = resp.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ProbeAuthError("데모 토큰 발급 응답에 access_token이 없음 — 서버 버전을 확인하세요.")
    return token


def _record_error(report: ProbeReport, key: str, sample: str) -> None:
    """실패 1건 회계 — 키(상태코드/예외 타입명)별 카운트 + 표본(최대 5건)."""
    report.http_errors[key] = report.http_errors.get(key, 0) + 1
    if len(report.error_samples) < 5:
        report.error_samples.append(sample)


def _drive_session(
    client: httpx.Client,
    headers: dict[str, str],
    shape: SessionShape,
    report: ProbeReport,
    *,
    pace: Callable[[], None] = lambda: None,
) -> None:
    """모양 1건 구동 — 세션 생성 1 + 턴 append 2. 실패는 회계 후 진행(never-break).

    pace: 쓰기 요청 *직전마다* 호출되는 페이싱 훅 — coach 쓰기 rate limit(기본 30/분,
    `coach_rate_limit_write_per_minute`)에 걸리지 않도록 run_probe가 sleep을 주입한다.
    2026-07-17 라이브 실측에서 무간격 제출 45쓰기 중 5건이 HTTP 429로 거절된 교훈.
    """
    pace()
    try:
        resp = client.post(_SESSIONS_PATH, json=shape.payloads[0], headers=headers)
    except httpx.HTTPError as exc:
        # 네트워크 실패 — 타입명 회계·로그(침묵 실패 금지). 이 세션의 턴은 진행 불가.
        _record_error(report, type(exc).__name__, f"[{shape.label}] 세션 생성 {type(exc).__name__}")
        logger.warning("세션 생성 실패(%s) — 모양 %s 건너뜀", type(exc).__name__, shape.label)
        return
    if resp.status_code != 201:
        _record_error(
            report, str(resp.status_code), f"[{shape.label}] 세션 생성 HTTP {resp.status_code}"
        )
        return
    report.sessions_submitted[shape.label] = report.sessions_submitted.get(shape.label, 0) + 1
    dialogue_id = resp.json().get("dialogue_id")
    if not isinstance(dialogue_id, str) or not dialogue_id:
        # 201인데 dialogue_id 부재 — 응답 계약 밖. 턴 진행 불가를 정직 회계.
        _record_error(report, "no_dialogue_id", f"[{shape.label}] 201 응답에 dialogue_id 없음")
        return
    for payload in shape.payloads[1:]:
        pace()
        try:
            turn = client.post(
                f"{_SESSIONS_PATH}/{dialogue_id}/turns", json=payload, headers=headers
            )
        except httpx.HTTPError as exc:
            _record_error(report, type(exc).__name__, f"[{shape.label}] 턴 {type(exc).__name__}")
            logger.warning(
                "턴 제출 실패(%s) — 모양 %s 다음 턴 진행", type(exc).__name__, shape.label
            )
            continue
        if turn.status_code != 201:
            _record_error(
                report, str(turn.status_code), f"[{shape.label}] 턴 HTTP {turn.status_code}"
            )
            continue
        report.turns_submitted[shape.label] = report.turns_submitted.get(shape.label, 0) + 1


def run_probe(
    *,
    base_url: str,
    rounds: int = 1,
    mix: dict[str, int] | None = None,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    delay_s: float = 2.5,
    sleeper: Callable[[float], None] | None = None,
) -> ProbeReport:
    """대표 3모양 합성 트래픽을 coach API로 제출하고 제출 회계를 반환한다.

    `client` 주입 시(테스트 — `httpx.MockTransport`) 그 클라이언트를 그대로 쓰고 닫지 않는다
    (소유권은 호출자). 미주입이면 `base_url`로 동기 클라이언트를 만들어 finally에서 닫는다.
    `token` 미지정이면 데모 콜백으로 자동 발급한다(실패 시 `ProbeAuthError` — 안내 동봉).

    delay_s: 쓰기 요청 간 간격(초). coach 쓰기 rate limit 기본 30/분에 맞춰 기본 2.5초
    (→ 24쓰기/분 < 30). 2026-07-17 라이브 실측에서 무간격 제출이 429 5건을 맞은 교훈 —
    0이면 페이싱 없음(테스트·rate limit 비활성 환경 전용). sleeper는 테스트 주입용
    (기본 time.sleep).
    """
    resolved_mix = dict(mix) if mix is not None else parse_mix(DEFAULT_MIX)
    plan = build_probe_plan(resolved_mix, rounds)
    owns_client = client is None
    http = client if client is not None else httpx.Client(base_url=base_url, timeout=timeout)
    do_sleep = sleeper if sleeper is not None else time.sleep
    pace: Callable[[], None] = (lambda: do_sleep(delay_s)) if delay_s > 0 else (lambda: None)
    try:
        auto_issued = token is None
        bearer = token if token is not None else issue_demo_token(http)
        headers = {"Authorization": f"Bearer {bearer}"}
        report = ProbeReport(
            base_url=base_url, rounds=rounds, mix=resolved_mix, token_auto_issued=auto_issued
        )
        for shape in plan:
            _drive_session(http, headers, shape, report, pace=pace)
        return report
    finally:
        if owns_client:
            http.close()


def render_report(report: ProbeReport) -> str:
    """사람용 제출 회계 — verdict는 싣지 않는다(서버 로그가 진실·harvest 안내만)."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("WH-1 shadow 합성 트래픽 드라이버 — 제출 회계(verdict 없음)")
    lines.append("=" * 64)
    lines.append(f"대상: {report.base_url}  ·  라운드: {report.rounds}  ·  믹스: {report.mix}")
    lines.append(f"토큰: {'데모 콜백 자동 발급' if report.token_auto_issued else '--token 주입'}")
    lines.append("[모양별 제출 — 세션 생성 / 턴 append 성공 수]")
    for label, shape in SHAPES.items():
        sessions = report.sessions_submitted.get(label, 0)
        turns = report.turns_submitted.get(label, 0)
        lines.append(f"  {label:<5}: 세션 {sessions} · 턴 {turns} — {shape.description}")
    lines.append(f"[HTTP 오류 회계] 총 {report.total_errors}건")
    for key, count in sorted(report.http_errors.items()):
        lines.append(f"  {key}: {count}건")
    for sample in report.error_samples:
        lines.append(f"  표본: {sample}")
    lines.append("=" * 64)
    lines.append("★ 합성 트래픽이다 — 실 학생 분포의 대표성 판정은 사람(Kiki) 몫.")
    lines.append("★ verdict는 서버 shadow 로그가 진실 — 다음으로 수확한다:")
    lines.append("  python -m whymath_backend.harness.wh1_shadow_harvest <서버로그> --store <원장>")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 제출 후 회계 출력. 전 제출 성공 0·오류/인증 실패 2."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.wh1_shadow_probe",
        description=(
            "WH-1 shadow 합성 트래픽 드라이버 — coach 세션/턴 API에 대표 3모양(eq/expr/bad) "
            "풀이 단계를 제출해 shadow verify verdict를 유도한다(verdict 수확은 "
            "wh1_shadow_harvest)."
        ),
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://127.0.0.1:8000",
        help="대상 서버 base URL(기본 http://127.0.0.1:8000).",
    )
    parser.add_argument("--rounds", type=int, default=1, help="믹스 반복 배수(표본 크기).")
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="기존 JWT 주입(미지정 시 /v1/auth/demo/callback 자동 발급 — 데모 서버 전제).",
    )
    parser.add_argument(
        "--mix",
        type=str,
        default=DEFAULT_MIX,
        help=f"모양 믹스(라운드당 세션 수) — 기본 {DEFAULT_MIX!r}.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.5,
        help=(
            "쓰기 요청 간 간격(초) — coach 쓰기 rate limit 30/분 대응(기본 2.5 → 24쓰기/분). "
            "0=페이싱 없음(rate limit 비활성 환경 전용·429 유발 주의)."
        ),
    )
    args = parser.parse_args(argv)
    base_url: str = args.base_url
    rounds: int = args.rounds
    token: str | None = args.token
    mix_spec: str = args.mix
    delay_s: float = args.delay

    try:
        mix = parse_mix(mix_spec)
        report = run_probe(base_url=base_url, rounds=rounds, mix=mix, token=token, delay_s=delay_s)
    except (ValueError, ProbeAuthError) as exc:
        print(f"프로브 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_ERROR

    print(render_report(report))
    return _EXIT_OK if report.total_errors == 0 else _EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, run_probe/main이 테스트 대상
    sys.exit(main())
