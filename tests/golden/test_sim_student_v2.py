"""S18 학생 모델(`golden.sim.student`) — 규칙 발화 · 주입기 답 포함 · 프라이버시 · 시드 없음 · 시드 반출 금지.

S11의 `test_sim_student.py`(옛 시뮬레이터 `golden/sim_student.py`)가 이미 있어 이름을 `_v2`로 했다.
실제 LLM은 부르지 않는다 — 로컬 Ollama 경로는 가짜 ollama 클라이언트를 주입해 확인한다.

지시서 S18 할 일 6:
① P1·P5·P7·P8 규칙 발화 ② forced_answer 포함 보장 ③ 프라이버시 검사가 닉네임·정답 혼입을 막는다
④ 시드 파일이 없을 때 명확한 오류. 그리고 완료 기준 ⑤ 시드가 클라우드 호출 경로에 들어가지 않는다.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
from golden.problems import Problem, load_problems
from golden.sim.ollama_client import FixedModelOllamaProvider

from golden import grade
from golden.sim import student, student_compare
from whymath_backend.l3.data_export_policy import export_judgment
from whymath_backend.l3.models import CostTier

_GOLDEN_PKG = Path(student.__file__).resolve().parents[1]
_PROBLEMS = load_problems()
_FAKE_SEEDS = [f"말투예시{chr(0xAC00 + i)} ㅁㄹ" for i in range(student.SEED_COUNT)]


def _p(pid: str) -> Problem:
    return next(p for p in _PROBLEMS if p["id"] == pid)


def _hist(n: int) -> list[dict[str, object]]:
    """튜터 되묻기 n턴이 지난 대화(이번 입력은 n+1번째)."""
    return [{"student": "음", "tutor": "어디가 막혀?"} for _ in range(n)]


class _FakeClient:
    """받은 호출을 기록하고 정해 둔 텍스트를 돌려주는 가짜 ollama 클라이언트."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return {"response": self.text, "model": "fake:1b"}

    async def list(self) -> Any:
        return {"models": []}


def _provider(text: str) -> tuple[FixedModelOllamaProvider, _FakeClient]:
    client = _FakeClient(text)
    return FixedModelOllamaProvider("fake:1b", client=client), client


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """실제 모드(가짜 모드 끔) + 가짜 시드 20줄 폴더. 클라우드 제공자는 부르면 터지게 막는다."""
    monkeypatch.delenv("GOLDEN_FAKE_LLM", raising=False)
    (tmp_path / "utterances.txt").write_text(
        "".join(f"{s}\tself\n" for s in _FAKE_SEEDS), encoding="utf-8"
    )
    monkeypatch.setenv(student.SEED_DIR_ENV, str(tmp_path))

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("학생 모델 경로가 클라우드 제공자를 불렀다")

    import golden.llm.factory as factory
    import golden.llm.openrouter as openrouter

    monkeypatch.setattr(factory, "build_cloud_provider", _boom)
    monkeypatch.setattr(openrouter.OpenRouterProvider, "generate", _boom)
    return tmp_path


# ── ① 규칙 발화(P1·P5·P7·P8) ────────────────────────────────────────────────


@pytest.mark.parametrize("fake", [True, False])
def test_rule_personas_never_call_llm(monkeypatch: pytest.MonkeyPatch, fake: bool) -> None:
    # 규칙 페르소나는 가짜 모드든 실제 모드든 같은 경로 — 로컬 모델·시드 없이 돈다
    if not fake:
        monkeypatch.delenv("GOLDEN_FAKE_LLM", raising=False)
        monkeypatch.setenv(student.SEED_DIR_ENV, "/없는/폴더")
    provider, client = _provider("불리면 안 된다")
    for persona in sorted(student.RULE_PERSONAS):
        for problem in _PROBLEMS:
            for n in range(4):
                student.reply(persona, problem, _hist(n), None, provider=provider)
    assert client.calls == []


def test_p1_demands_answer_every_turn() -> None:
    lines = [student.reply("P1", _p("LF-01"), _hist(n)) for n in range(4)]
    assert lines == [student.P1_LINE] * 4  # 2턴째도 같은 말(공유 계약)
    assert "답" in student.P1_LINE


def test_p5_gives_correct_answer_that_grader_accepts_and_asks_to_check() -> None:
    # M3 기준선: P5의 발화는 30문항 × 3턴 모두 채점기가 정답으로 판정해야 한다
    for problem in _PROBLEMS:
        for n in range(3):
            line = student.reply("P5", problem, _hist(n))
            assert grade.is_correct(problem, line), (problem["id"], line)
            assert any(line.endswith(t.strip()) for t in student.P5_TAILS)
            assert "\n" not in line and len(line) <= student.MAX_REPLY_LEN


def test_p5_form_that_grader_rejects_is_not_used() -> None:
    # "맞아요?" 꼬리는 normalize가 떼지 못해 정답이 오답이 된다(S18 실측) — 그래서 쓰지 않는다
    assert not grade.is_correct(_p("LF-01"), "-12 맞아요?")
    assert all("맞아요" not in t for t in student.P5_TAILS)


def test_p7_cycles_four_hostile_inputs_with_paste_exception() -> None:
    seen = {student.reply("P7", p, _hist(n)) for p in _PROBLEMS for n in range(4)}
    assert seen == set(student.P7_INPUTS)
    assert "" in seen  # 빈 입력
    assert re.search(r"[A-Za-z]{4,}", student.P7_INPUTS[1])  # 영어
    assert len(student.P7_PASTE) == student.PASTE_LEN == 500  # 500자 붙여넣기(상한 예외)
    for line in seen:
        assert "\n" not in line
        assert len(line) <= student.MAX_REPLY_LEN or line == student.P7_PASTE


def test_p8_types_a_random_wrong_number_or_forced_answer() -> None:
    for problem in _PROBLEMS:
        for n in range(4):
            line = student.reply("P8", problem, _hist(n))
            assert re.fullmatch(r"-?\d+", line), line
            assert not grade.is_correct(problem, line)  # 우연히 정답이 되지 않게
            assert line == student.reply("P8", problem, _hist(n))  # 결정적
    assert student.reply("P8", _p("LF-01"), [], "12") == "12"


def test_only_eight_personas_and_unknown_is_refused() -> None:
    assert list(student.PERSONAS) == [f"P{i}" for i in range(1, 9)]
    assert student.RULE_PERSONAS | student.LLM_PERSONAS == set(student.PERSONAS)
    assert not (student.RULE_PERSONAS & student.LLM_PERSONAS)
    with pytest.raises(student.StudentSimError):
        student.reply("P9", _p("LF-01"), [])


def test_personas_doc_matches_contract_and_has_no_digits() -> None:
    sections = student.persona_sections()
    assert set(sections) == {"공통 말투", *student.PERSONAS}
    text = student.PERSONAS_PATH.read_text(encoding="utf-8")
    assert not re.search(r"^## P9", text, re.MULTILINE)
    # 지시문 본문에 숫자가 있으면 프라이버시 검사(정답 혼입)가 우연히 걸릴 수 있다
    for title, body in sections.items():
        assert not re.search(r"[0-9]", body), title


# ── ② forced_answer 포함 보장 ─────────────────────────────────────────────


def test_fake_mode_includes_forced_answer() -> None:
    problem = _p("LF-01")
    for n in range(4):
        assert "12" in student.reply("P3", problem, _hist(n), "12")  # P3는 세션 내내
    assert student.reply("P2", problem, [], "12") == "12"  # P2 첫 입력 = 주입기 답
    assert grade.is_correct(problem, student.reply("P2", problem, _hist(1), "12"))  # 그다음 정답


def test_fake_mode_scripts_for_p4_p6() -> None:
    problem = _p("LF-13")
    assert student.reply("P4", problem, []).endswith("?")
    assert grade.is_correct(problem, student.reply("P4", problem, _hist(1)))
    assert not re.search(r"[0-9]", student.reply("P6", problem, []))
    assert grade.is_correct(problem, student.reply("P6", problem, _hist(1)))


def test_p3_requires_forced_answer() -> None:
    with pytest.raises(student.StudentSimError, match="forced_answer"):
        student.reply("P3", _p("LF-01"), [])


def test_live_keeps_model_line_that_contains_forced(live: Path) -> None:
    provider, client = _provider("나: 12 아님?\n둘째 줄")
    line = student.reply("P3", _p("LF-01"), [], "12", provider=provider)
    assert line == "12 아님?"  # 머리말·둘째 줄 제거
    assert len(client.calls) == 1


@pytest.mark.parametrize("text", ["모르겠는데요", "1 2 3", "가" * 99 + "12"])
def test_live_replaces_line_missing_forced(live: Path, text: str) -> None:
    # 빼먹었거나, 100자 상한에 잘려 사라졌으면 규칙 문장으로 바꾼다
    provider, _ = _provider(text)
    line = student.reply("P3", _p("LF-01"), [], "12", provider=provider)
    assert "12" in line and len(line) <= student.MAX_REPLY_LEN


def test_live_output_is_one_line_within_limit(live: Path) -> None:
    provider, _ = _provider("\n\n  “" + "아" * 300 + "”\n다음 줄")
    line = student.reply("P4", _p("LF-13"), [], provider=provider)
    assert "\n" not in line and len(line) == student.MAX_REPLY_LEN


# ── ③ 프라이버시 검사 ──────────────────────────────────────────────────────


def test_privacy_blocks_forced_answer_equal_to_correct(live: Path) -> None:
    provider, client = _provider("-12")
    with pytest.raises(student.PrivacyViolationError, match="정답"):
        student.reply("P3", _p("LF-01"), [], "-12", provider=provider)
    assert client.calls == []  # 보내기 전에 멈춘다


def test_privacy_blocks_nickname_in_prompt(live: Path) -> None:
    provider, client = _provider("음")
    history = [{"student": "몰라", "tutor": "sim-P2-1 학생, 어디가 막혔어?"}]
    with pytest.raises(student.PrivacyViolationError, match="닉네임"):
        student.reply(
            "P2", _p("LF-01"), history, identifiers=("sim-P2-1", "0f0e-uuid"), provider=provider
        )
    assert client.calls == []


def test_privacy_has_no_false_positive_on_any_problem() -> None:
    # 변별력의 반대쪽: 정상 입력(30문항 × LLM 페르소나 × 1~3번째 입력)은 하나도 막히지 않아야 한다
    for problem in _PROBLEMS:
        wrong = student_compare.demo_wrong_answer(problem)
        for persona in sorted(student.LLM_PERSONAS):
            for n in range(3):
                forced = wrong if persona in ("P2", "P3") else None
                prompt = student.build_prompt(persona, problem, _hist(n), forced, _FAKE_SEEDS)
                student.check_prompt_privacy(
                    prompt, identifiers=("sim-P2-1",), answer=problem["answer"]
                )


@pytest.mark.parametrize(
    ("text", "answer", "hit"),
    [
        ("네가 낼 답은 3 이다", "3", True),
        ("네가 낼 답은 -3 이다", "3", False),  # -3 안의 3은 정답 3이 아니다
        ("네가 낼 답은 3/2 이다", "3", False),
        ("네가 낼 답은 y=2x+3 이다", "2*x + 3", True),
        ("네가 낼 답은 3x+2 이다", "2*x + 3", False),
        ("네가 낼 답은 -12 이다", "12", False),
        ("12같아요", "12", True),
    ],
)
def test_contains_answer_boundary(text: str, answer: str, hit: bool) -> None:
    assert student.contains_answer(text, answer) is hit


def test_demo_wrong_answer_is_never_correct() -> None:
    for problem in _PROBLEMS:
        assert not grade.is_correct(problem, student_compare.demo_wrong_answer(problem))


# ── ④ 시드 파일 없음 → 명확한 오류 ─────────────────────────────────────────


def test_missing_seed_file_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(student.SeedFileMissingError, match="시드 발화 파일이 없다") as info:
        student.load_seed_utterances(tmp_path)
    assert str(tmp_path) in str(info.value)


def test_wrong_seed_count_raises(tmp_path: Path) -> None:
    (tmp_path / "utterances.txt").write_text("하나\tself\n둘\tadult\n", encoding="utf-8")
    with pytest.raises(student.SeedFileMissingError, match="2줄"):
        student.load_seed_utterances(tmp_path)


def test_live_llm_persona_without_seed_stops_before_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GOLDEN_FAKE_LLM", raising=False)
    monkeypatch.setenv(student.SEED_DIR_ENV, str(tmp_path / "없음"))
    provider, client = _provider("음")
    with pytest.raises(student.SeedFileMissingError):
        student.reply("P2", _p("LF-01"), [], provider=provider)
    assert client.calls == []  # 침묵 금지 — 시드 없이 조용히 돌지 않는다


# ── ⑤ 시드는 로컬 Ollama로만(공통 규칙 7) ──────────────────────────────────


def test_seed_goes_only_to_local_ollama(live: Path) -> None:
    provider, client = _provider("2 아님?")
    student.reply("P2", _p("LF-13"), [], provider=provider)
    assert len(client.calls) == 1
    system = client.calls[0]["system"]
    assert all(s in system for s in _FAKE_SEEDS)  # 시드는 로컬 호출의 시스템 프롬프트에 있다
    assert client.calls[0]["model"] == "fake:1b"


def test_student_routing_is_local_and_export_blocked() -> None:
    decision = student.local_decision()
    assert decision.cost_tier == CostTier.LOCAL
    # 요금 규칙이 바뀌어도 LOCAL이 유지되는 근거 — 선언 등급이 국외 반출 금지다
    assert export_judgment(student._routing_request().data_licenses).blocks_offshore


def test_default_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(student.STUDENT_MODEL_ENV, raising=False)
    assert student.student_model() == student.DEFAULT_STUDENT_MODEL
    monkeypatch.setenv(student.STUDENT_MODEL_ENV, "exaone3.5:7.8b")
    assert student.student_model() == "exaone3.5:7.8b"


_SIM_MODULES = ("student.py", "student_compare.py", "ollama_client.py")
_CLOUD_MODULES = ("golden.llm.factory", "golden.llm.openrouter", "golden.llm.gate", "golden.tutor")
_CLOUD_MODULES += ("golden.api", "whymath_backend.l3.providers")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_sim_student_modules_do_not_import_cloud_providers() -> None:
    for name in _SIM_MODULES:
        found = _imports(_GOLDEN_PKG / "sim" / name)
        assert found, name  # 0건 스캔은 통과가 아니다
        bad = {m for m in found if any(m == c or m.startswith(c + ".") for c in _CLOUD_MODULES)}
        assert bad == set(), (name, bad)


_SEED_NAMES = {"load_seed_utterances", "SEED_DIR", "seed_dir", "SEED_DIR_ENV", "utterances.txt"}
_CLOUD_NAMES = {"build_cloud_provider", "OpenRouterProvider", "guard_cloud_jurisdiction"}


def _names(func: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.update(n for n in _SEED_NAMES if n in node.value)
    return out


def test_no_function_reads_seed_and_calls_cloud() -> None:
    # 공통 규칙 7 동결: 골든 패키지 전체에서 "시드를 읽는 함수"와 "클라우드 제공자를 부르는 함수"가 같으면 RED
    seed_funcs = 0
    for path in sorted(_GOLDEN_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = _names(node)
            if names & _SEED_NAMES:
                seed_funcs += 1
                assert not (names & _CLOUD_NAMES), f"{path.name}:{node.name}"
    assert seed_funcs >= 2  # 스캔이 시드 읽는 함수를 실제로 찾았다(공허한 통과 방지)


# ── 모델 비교 도구(Kiki 머신용)의 순수 부분 ──────────────────────────────────


def test_discrimination_accuracy_separates_different_styles() -> None:
    human = ["ㅁㄹ요", "x는 몇임?", "ㅋㅋ 몰라", "이거 뭐임"]
    model = [
        "답은 다음과 같습니다.",
        "계산하면 결과가 나옵니다.",
        "따라서 정답입니다.",
        "다음과 같습니다.",
    ]
    assert student_compare.discrimination_accuracy(human, model) == 1.0


@pytest.mark.parametrize(
    ("persona", "line", "forced", "kinds"),
    [
        ("P2", "모르겠어요", None, ["수·식 없음"]),
        ("P2", "3 같아요", None, []),
        ("P3", "음 몰라", "12", ["주입기 답 없음"]),
        ("P3", "1 2 3", "12", ["주입기 답 없음"]),
        ("P3", "12 아님?", "12", []),
        ("P4", "기울기가 뭐예요?", None, []),
        ("P4", "답은 3", None, ["질문 아님"]),
        ("P6", "배고파 3시", None, ["잡담에 숫자"]),
        ("P6", "", None, ["빈 출력"]),
    ],
)
def test_rule_violations(persona: str, line: str, forced: str | None, kinds: list[str]) -> None:
    assert student_compare.rule_violations(persona, line, 1, forced) == kinds


def test_choose_prefers_fewer_violations_then_lower_accuracy() -> None:
    a = {"model": "a", "violations_total": 2, "discrimination_accuracy": 0.5, "seed_copies": 0}
    b = {"model": "b", "violations_total": 1, "discrimination_accuracy": 0.9, "seed_copies": 3}
    c = {"model": "c", "violations_total": 1, "discrimination_accuracy": 0.6, "seed_copies": 0}
    assert student_compare.choose([a, b]) == "b"
    assert student_compare.choose([a, b, c]) == "c"


def test_compare_fake_samples_has_eight_personas(tmp_path: Path) -> None:
    assert student_compare.main(["--fake", "--out", str(tmp_path)]) == 0
    text = (tmp_path / "samples.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if re.match(r"^\| P\d ", ln)]
    assert [r.split()[1] for r in rows] == list(student.PERSONAS)
    assert all(r.count(" | ") == len(student_compare.SAMPLE_PROBLEMS) for r in rows)


def test_compare_refuses_without_seed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GOLDEN_FAKE_LLM", raising=False)
    monkeypatch.setenv(student.SEED_DIR_ENV, str(tmp_path / "없음"))
    assert student_compare.main(["--out", str(tmp_path)]) == 2
    assert not (tmp_path / "model_compare.json").exists()


def test_compare_runs_with_fake_ollama(
    live: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 실제 데몬 대신 가짜 클라이언트 — 모델 2개 · 숫자만 담긴 결과 파일 · 시드 복제는 가린다
    def _fake_provider(model: str, **_k: object) -> FixedModelOllamaProvider:
        text = _FAKE_SEEDS[0] if model == "copycat:1b" else "기울기가 뭐예요?"
        return FixedModelOllamaProvider(model, client=_FakeClient(text))

    monkeypatch.setattr(student_compare, "FixedModelOllamaProvider", _fake_provider)
    out = tmp_path / "out"
    assert student_compare.main(["--models", "copycat:1b,asker:1b", "--out", str(out)]) == 0
    summary = (out / "model_compare.json").read_text(encoding="utf-8")
    assert all(s not in summary for s in _FAKE_SEEDS)  # 결과 파일에 시드 원문 없음
    samples = (out / "samples.md").read_text(encoding="utf-8")
    assert all(s not in samples for s in _FAKE_SEEDS)
    assert '"comparison": "실시"' in summary
    assert '"seed_copies": 20' in summary  # copycat은 4페르소나 × 5문항 전부 시드 복제


def test_reply_async_usable_inside_event_loop() -> None:
    # 러너(S19)는 이벤트 루프 안에서 부른다 — 비동기판이 있어야 한다
    async def _go() -> str:
        return await student.reply_async("P5", _p("LF-01"), [])

    assert grade.is_correct(_p("LF-01"), asyncio.run(_go()))


class _RaisingClient(_FakeClient):
    """호출마다 정해 둔 예외를 던지는 가짜 클라이언트."""

    def __init__(self, exc: Exception) -> None:
        super().__init__("")
        self.exc = exc

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        raise self.exc


def test_retryable_failure_is_retried_then_stops(live: Path) -> None:
    client = _RaisingClient(ConnectionError("데몬 꺼짐"))
    provider = FixedModelOllamaProvider("fake:1b", client=client)
    with pytest.raises(student.StudentSimError, match="ConnectionError"):
        student.reply("P2", _p("LF-01"), [], provider=provider)
    assert len(client.calls) == student.STUDENT_LLM_TRIES


def test_non_retryable_failure_propagates(live: Path) -> None:
    # 모델 없음 같은 오류는 다시 해도 같다 — 삼키지 않고 그대로 올린다(1회 호출)
    class ModelMissingError(Exception):
        pass

    client = _RaisingClient(ModelMissingError("model not found"))
    provider = FixedModelOllamaProvider("fake:1b", client=client)
    with pytest.raises(ModelMissingError):
        student.reply("P2", _p("LF-01"), [], provider=provider)
    assert len(client.calls) == 1


def test_empty_model_output_is_retried(live: Path) -> None:
    provider, client = _provider("  \n  ")
    with pytest.raises(student.StudentSimError, match="ValueError"):
        student.reply("P2", _p("LF-01"), [], provider=provider)
    assert len(client.calls) == student.STUDENT_LLM_TRIES


def test_non_local_routing_decision_stops_before_call(
    live: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 라우터 규칙이 바뀌어 클라우드 결정이 나와도 학생 모델은 보내지 않고 멈춘다
    from whymath_backend.l3.models import RoutingDecision
    from whymath_backend.l3.router import Router

    cloud = RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="t",
        est_latency_ms=1.0,
        est_cost_krw=1.0,
    )
    monkeypatch.setattr(Router, "route", lambda self, req: cloud)
    provider, client = _provider("2")
    with pytest.raises(student.StudentSimError, match="LOCAL이 아닌"):
        student.reply("P2", _p("LF-01"), [], provider=provider)
    assert client.calls == []


def test_seed_leak_scan_catches_long_and_short_seeds() -> None:
    row = "| P2 시도형 | 모델이 말투예시가 ㅁㄹ 를 그대로 씀 | 몰라 |"
    assert student_compare.seed_leaks([row], ["말투예시가 ㅁㄹ"]) == 1  # 긴 시드 — 부분 문자열
    assert student_compare.seed_leaks([row], ["몰라"]) == 1  # 짧은 시드 — 칸 전체 일치
    assert student_compare.seed_leaks([row], ["모"]) == 0  # 짧은 시드의 부분 일치는 유출 아님
    assert student_compare.seed_leaks([row], ["다른 문장이다요"]) == 0


def test_math_only_seed_is_not_a_leak() -> None:
    # 답만 쓴 시드(`-12`·`y=2x+3`)는 문항 정답과 같은 공개 값 — 칸이 같아도 유출로 세지 않는다
    row = "| P2 시도형 | -12 | y=2x+3 |"
    assert student_compare.seed_leaks([row], ["-12", "y = 2x+3"]) == 0
    assert not student_compare.copies_seed("-12", ["-12"])
    assert student_compare.copies_seed(
        "음 몰라", ["음 몰라"]
    )  # 글자 섞인 짧은 시드는 줄 전체 일치면 복제


def _write_seeds(directory: Path, seeds: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "utterances.txt").write_text(
        "".join(f"{s}\tself\n" for s in seeds), encoding="utf-8"
    )


def test_seed_equal_to_rule_row_is_not_a_leak(
    live: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Kiki 머신 2026-11-20 재현: 사람이 우연히 규칙 페르소나 문장(P1)·수 답(P5·P8 칸)과 같은 말을 했다.
    # 코드가 쓴 칸은 시드에서 온 글이 아니므로 결과를 지우면 안 된다(전에는 COMPARE_EXIT=3).
    seeds = [student.P1_LINE, "-12", *_FAKE_SEEDS[: student.SEED_COUNT - 2]]
    _write_seeds(tmp_path / "seed", seeds)
    monkeypatch.setenv(student.SEED_DIR_ENV, str(tmp_path / "seed"))

    def _fake_provider(model: str, **_k: object) -> FixedModelOllamaProvider:
        return FixedModelOllamaProvider(model, client=_FakeClient("기울기가 뭐예요?"))

    monkeypatch.setattr(student_compare, "FixedModelOllamaProvider", _fake_provider)
    out = tmp_path / "out"
    assert student_compare.main(["--models", "asker:1b", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "SEED_SCAN llm_leaks=0 rule_or_header_matches=1 math_only_seeds=1" in printed
    assert all(s not in printed for s in seeds if len(s) > 3)  # 화면에는 숫자만


def test_compare_masks_model_line_that_copies_seed(
    live: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 모델이 시드를 앞뒤에 말을 붙여 베끼면 그 칸을 가리고, 결과에는 시드가 남지 않는다
    def _fake_provider(model: str, **_k: object) -> FixedModelOllamaProvider:
        return FixedModelOllamaProvider(model, client=_FakeClient(f"음 {_FAKE_SEEDS[3]} 요"))

    monkeypatch.setattr(student_compare, "FixedModelOllamaProvider", _fake_provider)
    out = tmp_path / "out"
    assert student_compare.main(["--models", "copy:1b", "--out", str(out)]) == 0
    samples = (out / "samples.md").read_text(encoding="utf-8")
    assert _FAKE_SEEDS[3] not in samples
    assert samples.count(student_compare.SEED_COPY_MASK) == 20
    assert '"seed_copies": 20' in (out / "model_compare.json").read_text(encoding="utf-8")


def test_compare_deletes_outputs_when_mask_misses(
    live: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 마지막 방어선: 가림이 놓쳐 시드가 모델 발화에 남으면 결과를 지우고 3
    def _fake_provider(model: str, **_k: object) -> FixedModelOllamaProvider:
        return FixedModelOllamaProvider(model, client=_FakeClient(f"음 {_FAKE_SEEDS[3]} 요"))

    monkeypatch.setattr(student_compare, "FixedModelOllamaProvider", _fake_provider)
    monkeypatch.setattr(student_compare, "copies_seed", lambda line, seeds: False)
    out = tmp_path / "out"
    assert student_compare.main(["--models", "copy:1b", "--out", str(out)]) == 3
    assert not (out / "samples.md").exists() and not (out / "model_compare.json").exists()


# ── 실제 실행 경로의 시드 복제 차단(학생 발화는 클라우드 튜터로 간다 · 공통 규칙 7) ──────────


def test_live_reply_replaces_exact_seed_copy(live: Path) -> None:
    before = student.STATS["seed_copy_fallbacks"]
    provider, _ = _provider(_FAKE_SEEDS[5])
    line = student.reply("P2", _p("LF-01"), [], provider=provider)
    assert line == student.FAKE_P2_NO_FORCED
    assert not student.copies_seed(line, _FAKE_SEEDS)
    assert student.STATS["seed_copy_fallbacks"] == before + 1  # 막은 횟수가 남는다(침묵 금지)


def test_live_reply_replaces_partial_seed_copy(live: Path) -> None:
    provider, _ = _provider(f"음 {_FAKE_SEEDS[7]} 요")
    line = student.reply("P4", _p("LF-13"), [], provider=provider)
    assert _FAKE_SEEDS[7] not in line
    assert line == student.fake_llm_reply("P4", _p("LF-13"), [], None)


def test_live_p3_seed_copy_keeps_forced_answer(live: Path) -> None:
    provider, _ = _provider(f"{_FAKE_SEEDS[2]} 12")
    line = student.reply("P3", _p("LF-01"), [], "12", provider=provider)
    assert _FAKE_SEEDS[2] not in line and "12" in line


def test_live_math_only_seed_equal_is_kept(
    live: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 답만 쓴 시드(-12)와 모델 답이 같은 것은 복제가 아니다 — 학생 답을 바꾸면 안 된다
    _write_seeds(tmp_path / "seed", ["-12", *_FAKE_SEEDS[: student.SEED_COUNT - 1]])
    monkeypatch.setenv(student.SEED_DIR_ENV, str(tmp_path / "seed"))
    provider, _ = _provider("-12")
    assert student.reply("P2", _p("LF-01"), [], provider=provider) == "-12"


def test_compare_samples_rule_rows_match_header_problems(
    live: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 2026-11-20 Kiki 머신 결과: 규칙 행이 다른 문항 목록으로 만들어져 LF-18 칸에 LF-21 답이 들어갔다
    def _fake_provider(model: str, **_k: object) -> FixedModelOllamaProvider:
        return FixedModelOllamaProvider(model, client=_FakeClient("기울기가 뭐예요?"))

    monkeypatch.setattr(student_compare, "FixedModelOllamaProvider", _fake_provider)
    out = tmp_path / "out"
    assert student_compare.main(["--models", "asker:1b", "--out", str(out)]) == 0
    lines = (out / "samples.md").read_text(encoding="utf-8").splitlines()
    header = next(ln for ln in lines if ln.startswith("| 페르소나 |"))
    pids = [c.strip() for c in header.strip("|").split("|")][1:]
    p5 = next(ln for ln in lines if ln.startswith("| P5 "))
    cells = [c.strip() for c in p5.strip("|").split("|")][1:]
    assert pids == list(student_compare.COMPARE_PROBLEMS)
    assert all(grade.is_correct(_p(pid), cell) for pid, cell in zip(pids, cells, strict=True))
