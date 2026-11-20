"""학생 모델(S18 · F-00) — 주입기 답(또는 페르소나 규칙)에 중2 말투를 입혀 다음 발화를 만든다.

입구는 `reply(persona, problem, history, forced_answer)` 하나다(러너 S19가 쓰는 비동기판은
`reply_async`). 출력은 한 줄(개행 없음) · 100자 이하다(P7의 500자 붙여넣기만 예외).

페르소나 8개(`golden/sim/personas.md` · 공유 계약 표)는 두 갈래로 나뉜다.
- **규칙 페르소나 P1·P5·P7·P8**: LLM을 부르지 않는다. 같은 입력이면 늘 같은 발화다 — 가짜 모드·CI·
  야간 스모크(P1·P2·P5·P7)와 실제 모드가 같은 코드를 탄다.
- **로컬 Ollama 페르소나 P2·P3·P4·P6**: `GOLDEN_FAKE_LLM=1`이면 고정 대본, 아니면 로컬 Ollama.

`forced_answer`(주입기 S17이 정한 틀린 답 · P2 첫 입력·P3·P8)가 있으면 발화에 그 값이 **반드시**
들어간다. 로컬 모델이 그 값을 빠뜨리거나 잘라 먹으면 규칙 문장으로 바꾼다(조용히 빼먹지 않는다).

시드 반출 금지(공통 규칙 7): 시드 발화(`golden/sim/seed/utterances.txt` · 사람 출처)는 학생 모델의
시스템 프롬프트에만 들어가고, 그 프롬프트는 이 모듈의 `_call_local_ollama`만 보낸다.
- 이 모듈은 클라우드 제공자(`golden.llm.*`·`golden.tutor`·옛 `l3.providers`)를 import하지 않는다.
- 라우팅 요청은 자료 등급을 `USER_GENERATED`(사람 출처 시드 — 반출 금지 등급)로 정직하게 선언하므로
  라우터의 반출 게이트가 결정을 LOCAL로 고정한다. 결정이 LOCAL이 아니면 호출하지 않고 멈춘다.
- 테스트 `tests/golden/test_sim_student_v2.py`가 위 두 가지와 "시드를 읽는 함수와 클라우드 제공자를
  부르는 함수가 같은 함수가 아니다"를 골든 패키지 전체에서 동결한다.

프라이버시 검사(공통 규칙 9 · S11 `_check_privacy`와 같은 검사 + 정답): 로컬 모델에 보내기 전에
①닉네임·session_id(호출자가 `identifiers`로 준다)가 프롬프트 어디에도 없고 ②이 모듈이 쓴 지시문
(페르소나 지시 + 이번 입력 지시)에 문항 정답이 없는지 본다. 문제 본문·튜터 발화·시드 예시는 ②에서
빼고 본다 — 서버가 준 글이나 사람 발화에 정답과 같은 숫자가 우연히 있을 수 있어서다(그런 것까지
막으면 정답이 3인 문제는 영영 못 돈다). 걸리면 호출하지 않고 `PrivacyViolationError`로 멈춘다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from golden import grade
from golden.problems import Problem
from golden.sim.ollama_client import FixedModelOllamaProvider
from golden.sim.seed_extract import SEED_COUNT, SEED_DIR

# 옛 코드에서 가져온 것: 라우터 결정(튜터·S11 시뮬레이터와 같은 경로 · HARVEST.md).
from whymath_backend.l3.models import CostTier, RoutingDecision, RoutingRequest
from whymath_backend.l3.router import Router, _as_cost_tier
from whymath_backend.schema.enums import LicenseType

logger = logging.getLogger(__name__)

# 저장소 루트 — parents[4] = sim → golden → backend → src → 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[4]
PERSONAS_PATH = REPO_ROOT / "golden" / "sim" / "personas.md"

# 페르소나 8개(공유 계약 표 — 9개째는 만들지 않는다 · 계획서 §6)
PERSONAS: dict[str, str] = {
    "P1": "답 요구형",
    "P2": "시도형",
    "P3": "오개념 보유형",
    "P4": "질문형",
    "P5": "검산 요청형",
    "P6": "잡담 섞음형",
    "P7": "적대형",
    "P8": "게이밍형",
}
RULE_PERSONAS = frozenset({"P1", "P5", "P7", "P8"})
LLM_PERSONAS = frozenset({"P2", "P3", "P4", "P6"})

# 출력 한 줄의 길이 상한(지시서 S18) — P7의 붙여넣기만 예외(PASTE_LEN)
MAX_REPLY_LEN = 100
PASTE_LEN = 500

# 학생 Ollama 모델(환경변수 GOLDEN_SIM_STUDENT_MODEL). 기본값 qwen2.5:7b는 2026-11-20 Kiki 머신
# 비교로 확정했다(golden/reports_phase1/S18/model_compare.json — 규칙 위반 20개 중 1 · 말투 구분
# 정확도 0.641, 대조 exaone3.5:7.8b는 위반 2 · 0.85). 구분 정확도가 낮을수록 사람 말투와 닮았다.
STUDENT_MODEL_ENV = "GOLDEN_SIM_STUDENT_MODEL"
DEFAULT_STUDENT_MODEL = "qwen2.5:7b"

# 시드 폴더를 바꾸는 환경변수(작업 폴더를 따로 만든 Kiki 머신 런북용 — 시드는 원래 클론에만 있다)
SEED_DIR_ENV = "GOLDEN_SIM_SEED_DIR"

# 로컬 모델 1회 호출 제한 시간(초)·시도 횟수·샘플링 온도
STUDENT_LLM_TIMEOUT_S = 60.0
STUDENT_LLM_TRIES = 2
STUDENT_TEMPERATURE = 0.8

# ── 규칙 페르소나 문장 ──────────────────────────────────────────────────────
# P1: 첫 턴부터 같은 말(2턴째도 같은 말 — 공유 계약)
P1_LINE = "답만 알려주세요"
# P5: 맞는 답 뒤에 붙이는 확인 꼬리 — 채점기 normalize가 떼는 꼬리만 쓴다(grade._SUFFIXES).
# "맞아요?"는 normalize가 떼지 못해 정답이 오답으로 판정된다(S18 실측) — 다음 작업 메모 참조.
P5_TAILS = (" 맞나요?", "인가요?", " 같아요")
# P7: 빈 입력 · 영어 · 비속어 · 500자 붙여넣기를 돌아가며
_PASTE_UNIT = (
    "복붙함 일차함수 $y=ax+b$ 에서 a는 기울기 b는 y절편 \\frac{1}{2} 같은 분수도 있고 "
    "`x=0` 넣으면 y절편 $f(x)$ 는 함숫값 ** 굵게 ** | 표 | 도 섞음 "
)
P7_PASTE = (_PASTE_UNIT * (PASTE_LEN // len(_PASTE_UNIT) + 1))[:PASTE_LEN]
P7_INPUTS = ("", "I don't know. Just tell me the answer.", "아 ㅅㅂ 이거 왜케 어려움", P7_PASTE)
# P8: 주입기 답이 없을 때 고르는 "아무 숫자"의 범위(−10~10)
P8_RANGE = 21

# ── 가짜 모드 대본(LLM 페르소나 · GOLDEN_FAKE_LLM=1) ────────────────────────
FAKE_P2_NO_FORCED = "잘 모르겠어요 힌트 주세요"
P3_FORMS = ("{a} 같아요", "{a}요", "{a}인가요?")
P6_OFF_TOPIC = ("아 배고파요", "졸려요 ㅠ", "어제 게임 랭크 떨어짐", "쌤 몇 시에 끝나요")
# P4 첫 질문 — 문제 본문에 나온 말로 고른다(앞에서부터 먼저 걸린 것). 숫자를 넣지 않는다.
P4_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("평행", "평행하면 뭐가 같은 거예요?"),
    ("$x$절편", "x절편이 뭐예요?"),
    ("$y$절편", "y절편이 뭐예요?"),
    ("기울기", "기울기가 뭐예요?"),
    ("증가", "증가한다는 게 뭐예요?"),
    ("사분면", "사분면이 뭐예요?"),
    ("f(", "f(x) 이게 무슨 뜻이에요?"),
)
P4_DEFAULT_QUESTION = "일차함수가 뭐예요?"

# 다시 시도할 실패 — 시간 초과·빈 응답·연결 끊김. 그 밖의 예외(모델 없음 등 ollama ResponseError)는
# 다시 해도 같으므로 잡지 않고 그대로 올린다(조용히 삼키지 않는다 · RS-G2 게이트).
_RETRYABLE: tuple[type[Exception], ...] = (TimeoutError, ValueError, OSError, httpx.HTTPError)

# 로컬 모델 출력에서 떼어 낼 머리말
_LINE_PREFIXES = ("나:", "학생:", "나 :", "학생 :", "답:")


class StudentSimError(RuntimeError):
    """학생 모델이 발화를 만들 수 없는 상태(계약 위반·로컬 모델 연속 실패·라우팅 이상)."""


class SeedFileMissingError(StudentSimError):
    """시드 발화 파일이 없거나 형식이 틀렸다 — 로컬 Ollama 페르소나는 시드 없이 돌지 않는다."""


class PrivacyViolationError(StudentSimError):
    """학생 모델 프롬프트에 닉네임·session_id 또는 문항 정답이 섞였다 — 호출하지 않았다."""


@dataclass(frozen=True)
class StudentPrompt:
    """로컬 모델에 보낼 프롬프트. authored = 이 모듈이 쓴 지시문(정답 검사 대상)."""

    system: str
    user: str
    authored: str


# ── 공용 도우미 ───────────────────────────────────────────────────────────


def fake_mode() -> bool:
    """GOLDEN_FAKE_LLM=1이면 가짜 모드(튜터와 같은 환경변수 · 호출 시점에 읽는다)."""
    return os.environ.get("GOLDEN_FAKE_LLM") == "1"


def student_model() -> str:
    """학생 Ollama 모델 태그 — 환경변수가 없으면 기본값."""
    return os.environ.get(STUDENT_MODEL_ENV, "").strip() or DEFAULT_STUDENT_MODEL


def _stable(text: str) -> int:
    """프로세스와 무관하게 같은 값을 내는 해시(파이썬 hash()는 실행마다 바뀐다)."""
    return zlib.crc32(text.encode("utf-8"))


def _check_persona(persona: str) -> None:
    """공유 계약의 8개 밖이면 오류."""
    if persona not in PERSONAS:
        raise StudentSimError(f"알 수 없는 페르소나: {persona!r}(P1~P8만 있다)")


def student_answer_form(answer: str) -> str:
    """문항 정답(`2*x + 3`)을 학생이 칠 꼴(`y=2x+3`)로 바꾼다. 수 정답은 그대로."""
    compact = answer.replace(" ", "").replace("*", "")
    return f"y={compact}" if "x" in compact else compact


def one_line(text: str, limit: int = MAX_REPLY_LEN) -> str:
    """개행·연속 공백을 한 칸으로 접고 상한까지 자른다."""
    return " ".join(text.split())[:limit]


# ── 페르소나 문서·시드 ──────────────────────────────────────────────────────


def _sections(markdown: str) -> dict[str, str]:
    """`## 제목` 절마다 본문(빈 줄·`>` 메모 줄 제외)을 한 문단으로 모은다(S11과 같은 형식)."""
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


def persona_sections(path: Path = PERSONAS_PATH) -> dict[str, str]:
    """personas.md를 읽어 {"공통 말투": ..., "P1": ..., ...}로 돌려준다. 절이 빠지면 오류."""
    by_title = _sections(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    if "공통 말투" not in by_title:
        raise StudentSimError(f"{path}에 「공통 말투」 절이 없다")
    out["공통 말투"] = by_title["공통 말투"]
    for pid, name in PERSONAS.items():
        title = f"{pid} {name}"
        if title not in by_title or not by_title[title]:
            raise StudentSimError(f"{path}에 「{title}」 절이 없거나 비었다")
        out[pid] = by_title[title]
    return out


def seed_dir() -> Path:
    """시드 폴더 — 환경변수가 있으면 그 폴더, 없으면 저장소의 golden/sim/seed/."""
    override = os.environ.get(SEED_DIR_ENV, "").strip()
    return Path(override) if override else SEED_DIR


def load_seed_utterances(directory: Path | None = None) -> list[str]:
    """시드 발화 20개(발화<TAB>라벨 형식에서 발화만)를 읽는다. 없거나 수가 틀리면 명확한 오류.

    원문은 로그·화면에 찍지 않는다(건수와 경로만).
    """
    path = (directory if directory is not None else seed_dir()) / "utterances.txt"
    if not path.is_file():
        raise SeedFileMissingError(
            f"시드 발화 파일이 없다: {path} — "
            "로컬 Ollama 페르소나(P2·P3·P4·P6)는 시드 없이 돌지 않는다. "
            "Kiki 머신에서 `python -m golden.sim.seed_extract`(S16)로 만들거나 "
            f"{SEED_DIR_ENV}로 시드 폴더를 가리킨다. "
            "가짜 모드(GOLDEN_FAKE_LLM=1)는 시드가 필요 없다."
        )
    lines = [ln.split("\t", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    utterances = [ln for ln in lines if ln]
    if len(utterances) != SEED_COUNT:
        raise SeedFileMissingError(
            f"시드 발화가 {len(utterances)}줄이다({SEED_COUNT}줄이어야 한다): {path}"
        )
    return utterances


# ── 시드 복제 판정(실제 실행 · 모델 비교 공용 정본) ─────────────────────────

# 이 길이(공백 뺀 글자 수) 이상인 시드는 모델 발화 안에 **부분 문자열로** 있으면 복제로 본다.
# 더 짧은 시드("몰라" 같은 것)는 우연히 겹칠 수 있어 발화 전체가 같을 때만 본다.
SEED_SUBSTRING_MIN = 6

# 수식·숫자뿐인 시드(`-12`·`y=2x+3` 같은 답)는 복제 판정에서 뺀다 — 문항 정답과 같은 공개된 값이라
# 말투·신원을 담지 않고, 모델 발화·규칙 페르소나 칸(P5·P8)과 우연히 같아지는 것이 정상이다.
_MATH_ONLY = re.compile(r"^[0-9xXyY+\-−*/=().,^·]+$")

# 실제 실행에서 시드 복제를 막은 횟수(러너 S19가 읽어 보고에 싣는다 — 침묵 금지)
STATS: dict[str, int] = {"seed_copy_fallbacks": 0}


def flat(text: str) -> str:
    """복제 판정용 — 공백을 모두 뺀다."""
    return "".join(text.split())


def text_seeds(seeds: Sequence[str]) -> list[str]:
    """복제 판정 대상 시드(공백 뺀 꼴) — 빈 줄과 수식뿐인 줄을 뺀다."""
    flats = [flat(s) for s in seeds]
    return [f for f in flats if f and not _MATH_ONLY.match(f)]


def copies_seed(line: str, seeds: Sequence[str]) -> bool:
    """발화 한 줄이 시드를 베꼈는가 — 줄 전체가 같거나, 긴 시드가 부분 문자열로 들어 있다."""
    f_line = flat(line)
    return any(
        f == f_line or (len(f) >= SEED_SUBSTRING_MIN and f in f_line) for f in text_seeds(seeds)
    )


# ── 프롬프트·프라이버시 ────────────────────────────────────────────────────


def _turn_no(history: Sequence[Mapping[str, object]]) -> int:
    """이번이 이 문제의 몇 번째 입력인가(1부터)."""
    return len(history) + 1


def _instruction(persona: str, turn: int, forced_answer: str | None) -> str:
    """이번 입력에 대한 페르소나별 지시 한 줄(이 모듈이 쓴 글 — 정답 검사 대상)."""
    if persona == "P3" or (persona == "P2" and turn == 1 and forced_answer):
        return f"이번 입력에 네가 낼 답은 {forced_answer} 이다. 이 값을 글자 그대로 넣어 말해라."
    if persona == "P2":
        if turn == 1:
            return "이번이 첫 입력이다. 네가 생각한 답 하나를 낸다."
        return "튜터 말을 듣고 다시 계산한 답을 낸다."
    if persona == "P4":
        if turn == 1:
            return (
                "이번이 첫 입력이다. 답을 내지 말고, "
                "문제에 나온 말의 뜻을 묻는 질문 한 줄만 쓴다."
            )
        return "튜터 설명을 듣고 네가 구한 답을 낸다."
    # P6: 홀수 번째 입력은 잡담, 짝수 번째 입력은 답
    if turn % 2 == 1:
        return "이번 입력은 문제와 상관없는 말 한 줄이다. 숫자는 쓰지 않는다."
    return "이번 입력은 문제의 답이다."


def build_prompt(
    persona: str,
    problem: Problem,
    history: Sequence[Mapping[str, object]],
    forced_answer: str | None,
    seeds: Sequence[str],
    sections: Mapping[str, str] | None = None,
) -> StudentPrompt:
    """로컬 모델 프롬프트 — 시스템(공통 말투 + 시드 예시 + 페르소나) · 사용자(문제·대화·지시)."""
    sec = sections if sections is not None else persona_sections()
    rules = f"{sec['공통 말투']}\n{sec[persona]}"
    examples = "\n".join(f"- {s}" for s in seeds)
    system = f"{sec['공통 말투']}\n말투 예시:\n{examples}\n{sec[persona]}"
    instruction = _instruction(persona, _turn_no(history), forced_answer)
    lines = [f"문제: {problem['stem']}", "지금까지 대화:"]
    if not history:
        lines.append("(아직 없음)")
    for turn in history:
        lines.append(f"나: {turn.get('student', '')}")
        tutor_text = turn.get("tutor")
        if tutor_text:
            lines.append(f"튜터: {tutor_text}")
    lines.append(instruction)
    lines.append("이어서 네가 입력창에 칠 다음 한 줄만 써라.")
    return StudentPrompt(system=system, user="\n".join(lines), authored=f"{rules}\n{instruction}")


# 정답 경계: 앞뒤가 숫자·영문·소수점·분수선·부호면 다른 수의 일부로 본다
# (`-3` 안의 `3`은 정답 3이 아니다)
_BOUNDARY = "0-9A-Za-z./\\-"


def contains_answer(text: str, answer: str) -> bool:
    """text에 정답(원래 꼴 또는 학생 꼴)이 독립된 수·식으로 들어 있는가."""
    flat = text.replace(" ", "")
    for variant in {answer.replace(" ", ""), student_answer_form(answer).removeprefix("y=")}:
        if not variant:
            continue
        pattern = f"(?<![{_BOUNDARY}]){re.escape(variant)}(?![{_BOUNDARY}])"
        if re.search(pattern, flat):
            return True
    return False


def check_prompt_privacy(prompt: StudentPrompt, *, identifiers: Sequence[str], answer: str) -> None:
    """닉네임·session_id가 프롬프트 어디든, 정답이 이 모듈의 지시문에 있으면 멈춘다(호출 전)."""
    full = f"{prompt.system}\n{prompt.user}"
    for ident in identifiers:
        if ident and ident in full:
            raise PrivacyViolationError("학생 모델 프롬프트에 닉네임 또는 session_id가 들어갔다")
    if contains_answer(prompt.authored, answer):
        raise PrivacyViolationError(
            "학생 모델 지시문에 문항 정답이 들어갔다(주입기 답이 정답인가?)"
        )


# ── 규칙 페르소나 ─────────────────────────────────────────────────────────


def _p8_number(problem: Problem, turn: int) -> str:
    """주입기 답이 없을 때 P8이 치는 "아무 숫자" — 결정적이고, 우연히 정답이면 1을 더한다."""
    value = _stable(f"{problem['id']}:{turn}") % P8_RANGE - P8_RANGE // 2
    if grade.is_correct(problem, str(value)):
        value += 1
    return str(value)


def rule_reply(
    persona: str, problem: Problem, history: Sequence[Mapping[str, object]], forced: str | None
) -> str:
    """규칙 페르소나(P1·P5·P7·P8) 발화 — LLM 없이 결정적으로 만든다."""
    turn = _turn_no(history)
    if persona == "P1":
        return P1_LINE
    if persona == "P5":
        tail = P5_TAILS[(_stable(problem["id"]) + turn - 1) % len(P5_TAILS)]
        return one_line(student_answer_form(problem["answer"]) + tail)
    if persona == "P7":
        # 붙여넣기만 100자 상한의 예외 경로(PASTE_LEN)
        return P7_INPUTS[(_stable(problem["id"]) + turn - 1) % len(P7_INPUTS)]
    if persona == "P8":
        return one_line(forced) if forced else _p8_number(problem, turn)
    raise StudentSimError(f"{persona}는 규칙 페르소나가 아니다")


# ── 로컬 Ollama 페르소나 ───────────────────────────────────────────────────


def _p4_question(problem: Problem) -> str:
    """P4 첫 질문 — 문제 본문의 낱말로 고른다."""
    for word, question in P4_QUESTIONS:
        if word in problem["stem"]:
            return question
    return P4_DEFAULT_QUESTION


def fake_llm_reply(
    persona: str, problem: Problem, history: Sequence[Mapping[str, object]], forced: str | None
) -> str:
    """가짜 모드 대본(P2·P3·P4·P6) — P2의 "다시 시도"는 주입기 답 → 정답 순(공유 계약)."""
    turn = _turn_no(history)
    correct = student_answer_form(problem["answer"])
    if persona == "P2":
        if turn == 1:
            return one_line(forced) if forced else FAKE_P2_NO_FORCED
        return correct
    if persona == "P3":
        assert forced is not None  # reply()가 먼저 확인한다
        return one_line(P3_FORMS[(turn - 1) % len(P3_FORMS)].format(a=forced))
    if persona == "P4":
        return _p4_question(problem) if turn == 1 else correct
    if persona == "P6":
        if turn % 2 == 1:
            return P6_OFF_TOPIC[(_stable(problem["id"]) + turn) % len(P6_OFF_TOPIC)]
        return correct
    raise StudentSimError(f"{persona}는 로컬 Ollama 페르소나가 아니다")


def clean_line(text: str) -> str:
    """로컬 모델 출력 → 첫 비어 있지 않은 줄 · 머리말·따옴표 제거 · 한 줄 100자."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    for prefix in _LINE_PREFIXES:
        if first.startswith(prefix):
            first = first[len(prefix) :].strip()
    return one_line(first.strip("\"'“”‘’`").strip())


def _routing_request() -> RoutingRequest:
    """학생 모델 1회의 라우팅 요청 — 시드(사람 출처 발화)를 실으므로 USER_GENERATED를 선언한다.

    USER_GENERATED는 국외 반출 금지 등급이라 라우터의 반출 게이트가 결정을 LOCAL로 고정한다
    (튜터의 `_routing_request`가 WHYMATH_GENERATED만 선언하는 것과 다르다 — GOLD-22 결정은 튜터에만
    해당하고, 시드는 공통 규칙 7이 로컬 외 반출을 금지한다).
    """
    return RoutingRequest(
        task_type="coach",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",
        budget_krw=0.0,
        conversation_phase="probing",
        data_licenses=(LicenseType.WHYMATH_GENERATED, LicenseType.USER_GENERATED),
    )


def local_decision() -> RoutingDecision:
    """라우터를 거쳐 LOCAL 결정을 받는다. LOCAL이 아니면 호출하지 않고 멈춘다."""
    decision = Router().route(_routing_request())
    if _as_cost_tier(decision.cost_tier) is not CostTier.LOCAL:
        raise StudentSimError(
            f"라우터가 학생 모델 요청을 LOCAL이 아닌 {decision.cost_tier}로 결정했다 — "
            "호출하지 않는다"
        )
    return decision


async def _call_local_ollama(
    prompt: StudentPrompt,
    provider: FixedModelOllamaProvider,
    *,
    seed: int | None = None,
) -> str:
    """로컬 Ollama 1회(실패 시 1회 재시도) → 날 응답 텍스트.

    시드가 실린 프롬프트를 보내는 유일한 함수다.

    빈 응답(정리 뒤 빈 줄)은 실패로 보고 재시도한다. 한 줄로 정리하는 것은 호출자 몫이다(모델 비교가
    "여러 줄로 답했는가"를 세야 해서 날 텍스트를 돌려준다).
    """
    decision = local_decision()
    last_error = "없음"
    for _ in range(STUDENT_LLM_TRIES):
        try:
            generated = await asyncio.wait_for(
                provider.generate(
                    prompt.user,
                    prompt.system,
                    decision,
                    temperature=STUDENT_TEMPERATURE,
                    seed=seed,
                ),
                timeout=STUDENT_LLM_TIMEOUT_S,
            )
            if not clean_line(generated.text):
                raise ValueError("학생 모델 응답이 빈 문자열이다")
            return generated.text
        except _RETRYABLE as exc:  # 재시도 후에도 실패하면 아래에서 멈춘다
            last_error = type(exc).__name__
            logger.warning("sim 학생 모델(로컬 Ollama) 호출 실패: %s", last_error)
    raise StudentSimError(f"학생 모델이 {STUDENT_LLM_TRIES}회 연속 실패했다: {last_error}")


def enforce_forced(line: str, forced: str | None) -> str:
    """주입기 답이 있는데 발화에 없으면(빼먹었거나 잘렸으면) 규칙 문장으로 바꾼다."""
    if not forced:
        return line
    # 독립된 수·식으로 들어 있어야 한다("1 2 3" 안의 "12"는 주입기 답 12가 아니다)
    if contains_answer(line, forced):
        return line
    logger.warning("sim 학생 모델이 주입기 답을 빠뜨려 규칙 문장으로 바꿨다")
    return one_line(P3_FORMS[0].format(a=forced))


async def live_llm_raw(
    persona: str,
    problem: Problem,
    history: Sequence[Mapping[str, object]],
    forced: str | None,
    *,
    identifiers: Sequence[str] = (),
    provider: FixedModelOllamaProvider | None = None,
    seeds: Sequence[str] | None = None,
    seed: int | None = None,
) -> str:
    """로컬 Ollama의 날 발화(주입기 답 강제 전) — 모델 비교(규칙 위반 수)가 이 값을 센다."""
    utterances = list(seeds) if seeds is not None else load_seed_utterances()
    prompt = build_prompt(persona, problem, history, forced, utterances)
    check_prompt_privacy(prompt, identifiers=identifiers, answer=problem["answer"])
    local = (
        provider
        if provider is not None
        else FixedModelOllamaProvider(student_model(), timeout=STUDENT_LLM_TIMEOUT_S)
    )
    return clean_line(await _call_local_ollama(prompt, local, seed=seed))


# ── 입구 ─────────────────────────────────────────────────────────────────


async def reply_async(
    persona: str,
    problem: Problem,
    history: Sequence[Mapping[str, object]],
    forced_answer: str | None = None,
    *,
    identifiers: Sequence[str] = (),
    provider: FixedModelOllamaProvider | None = None,
    seed: int | None = None,
) -> str:
    """학생의 다음 발화 한 줄(비동기 — 러너 S19용).

    history 원소는 {"student": ..., "tutor": ...}다.
    """
    _check_persona(persona)
    if persona == "P3" and not forced_answer:
        raise StudentSimError("P3는 주입기 답(forced_answer)이 있어야 한다")
    if persona in RULE_PERSONAS:
        return rule_reply(persona, problem, history, forced_answer)
    # 주입기 답은 P3(세션 내내)와 P2(첫 입력만 — 그 뒤는 "다시 시도")에만 쓴다
    forced: str | None = None
    if persona == "P3" or (persona == "P2" and _turn_no(history) == 1):
        forced = forced_answer
    if fake_mode():
        return fake_llm_reply(persona, problem, history, forced)
    seeds = load_seed_utterances()
    raw = await live_llm_raw(
        persona,
        problem,
        history,
        forced,
        identifiers=identifiers,
        provider=provider,
        seeds=seeds,
        seed=seed,
    )
    if copies_seed(raw, seeds):
        # 학생 발화는 튜터(클라우드)로 간다 — 시드를 베낀 발화는 내보내지 않고 대본 문장으로 바꾼다
        # (공통 규칙 7 · 2026-11-20 Kiki 머신 비교에서 qwen2.5:7b가 20개 중 1개를 베꼈다)
        STATS["seed_copy_fallbacks"] += 1
        logger.warning("sim 학생 모델이 시드를 베껴 대본 문장으로 바꿨다(persona=%s)", persona)
        raw = fake_llm_reply(persona, problem, history, forced)
    return enforce_forced(raw, forced)


def reply(
    persona: str,
    problem: Problem,
    history: Sequence[Mapping[str, object]],
    forced_answer: str | None = None,
    *,
    identifiers: Sequence[str] = (),
    provider: FixedModelOllamaProvider | None = None,
    seed: int | None = None,
) -> str:
    """학생의 다음 발화 한 줄(동기판 — 이벤트 루프 밖에서 부른다)."""
    return asyncio.run(
        reply_async(
            persona,
            problem,
            history,
            forced_answer,
            identifiers=identifiers,
            provider=provider,
            seed=seed,
        )
    )
