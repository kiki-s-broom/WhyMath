"""학생 모델 후보 비교(S18 할 일 4) — Kiki 머신에서 로컬 Ollama 모델 2개를 돌려 1개를 고른다.

실행(저장소의 src/backend 폴더 · Kiki 머신 · Ollama 데몬 가동 · 시드 파일 있음):
    python -m golden.sim.student_compare --models exaone3.5:7.8b,qwen2.5:7b

기준 두 가지(지시서):
- ⓑ 페르소나 규칙 준수 — 로컬 Ollama 페르소나(P2·P3·P4·P6) × 문항 5개의
  **날 발화**(주입기 답 강제 전)에서 규칙 위반을 센다. 위반 = 빈 출력 · 여러 줄 ·
  100자 초과 · P2 첫 입력에 수·식이 없음 · P3 발화에 주입기 답이 없음 ·
  P4 첫 입력이 질문이 아님 · P6 잡담 턴에 숫자가 있음. 적을수록 좋다.
- ⓐ 시드 말투 재현 — 지시서는 "세션 AI가 구분"이라고 했지만 시드는 로컬 밖으로
  보낼 수 없다(공통 규칙 7 — 규칙이 작업 지시보다 우선). 그래서 구분기를
  **로컬 결정론 계산**으로 바꿨다: 시드 20개와 모델 발화 20개를 섞어, 글자 2-gram
  빈도의 코사인 유사도로 한 개씩 빼고 나머지 두 무리의 중심 중 가까운 쪽으로
  맞히게 한다(leave-one-out 최근접 중심). 정확도가 50%에 가까울수록 구분이 안
  된다 = 말투가 닮았다. 낮을수록 좋다.
- 고르는 규칙: ⓑ 위반 수가 적은 쪽 → 같으면 ⓐ 정확도가 낮은 쪽 →
  같으면 시드 복제 수가 적은 쪽.

출력: `golden/reports_phase1/S18/model_compare.json`(숫자만 — 발화 원문 없음)과
`samples.md`(페르소나별 발화 5개 · 모델 출력만). 화면에도 숫자만 찍는다.
시드 원문은 어디에도 쓰지 않는다 — 모델 발화가 시드 한 줄과 글자가 같으면
(공백 무시) 샘플에서 "[시드 복제 — 가림]"으로 바꾸고 그 수를 센다.

`--fake`: Ollama 없이 가짜 모드 대본으로 samples.md만 쓴다(클라우드 세션·CI용 · 비교는 하지 않는다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import httpx
import sympy

from golden.problems import Problem, load_problems
from golden.sim import student
from golden.sim.ollama_client import FixedModelOllamaProvider

# 비교에 쓰는 문항 5개(유형이 겹치지 않게 — 함숫값·두 점 기울기·y절편·x절편·증가 개수)
COMPARE_PROBLEMS = ("LF-01", "LF-13", "LF-17", "LF-18", "LF-26")
# 샘플 문서용 문항 5개(식 정답 문항 하나를 넣어 P5의 `y=…` 꼴을 보인다)
SAMPLE_PROBLEMS = ("LF-01", "LF-13", "LF-17", "LF-21", "LF-26")
DEFAULT_MODELS = ("exaone3.5:7.8b", "qwen2.5:7b")
OUT_DIR = student.REPO_ROOT / "golden" / "reports_phase1" / "S18"
SEED_COPY_MASK = "[시드 복제 — 가림]"

# P4 첫 입력이 질문인지 보는 낱말
_QUESTION_WORDS = ("뭐", "왜", "어떻게", "무슨", "뜻", "어디", "무엇", "몰라", "모르")
_HAS_NUMBER = re.compile(r"[0-9]")


def demo_wrong_answer(problem: Problem) -> str:
    """비교·샘플용 고정 오답(주입기 S17 아님) — 수는 부호 반대(0이면 1), 식은 기울기·절편 뒤바꿈."""
    x = sympy.Symbol("x")
    expr = sympy.sympify(problem["answer"])
    if problem["answer_kind"] == "number":
        value = -expr if expr != 0 else sympy.Integer(1)
        return str(value).replace(" ", "")
    a, b = sympy.Poly(expr, x).all_coeffs()
    swapped = sympy.expand(b * x + a)
    return student.student_answer_form(str(swapped))


def _problem(pid: str) -> Problem:
    """문항 id로 문항 1개."""
    return next(p for p in load_problems() if p["id"] == pid)


def rule_violations(persona: str, line: str, raw_text_lines: int, forced: str | None) -> list[str]:
    """날 발화 1개의 규칙 위반 목록(첫 입력 기준)."""
    out: list[str] = []
    if not line:
        out.append("빈 출력")
    if raw_text_lines > 1:
        out.append("여러 줄")
    if len(line) > student.MAX_REPLY_LEN:
        out.append("100자 초과")
    if persona == "P2" and not (_HAS_NUMBER.search(line) or "x" in line):
        out.append("수·식 없음")
    if persona == "P3" and forced and not student.contains_answer(line, forced):
        out.append("주입기 답 없음")
    if persona == "P4" and not (line.endswith("?") or any(w in line for w in _QUESTION_WORDS)):
        out.append("질문 아님")
    if persona == "P6" and _HAS_NUMBER.search(line):
        out.append("잡담에 숫자")
    return out


# ── ⓐ 로컬 결정론 구분기 ────────────────────────────────────────────────────


def _bigrams(text: str) -> Counter[str]:
    """글자 2-gram 빈도(앞뒤에 경계 표시를 붙인다)."""
    s = f"^{text}$"
    return Counter(s[i : i + 2] for i in range(len(s) - 1))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    """두 빈도 벡터의 코사인 유사도(빈 벡터면 0)."""
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _centroid(vectors: Sequence[Counter[str]]) -> Counter[str]:
    """빈도 벡터들의 합(코사인은 크기와 무관하므로 평균 대신 합)."""
    total: Counter[str] = Counter()
    for v in vectors:
        total.update(v)
    return total


def discrimination_accuracy(human: Sequence[str], model: Sequence[str]) -> float:
    """leave-one-out 최근접 중심 정확도(0~1). 0.5에 가까울수록 두 무리를 못 가른다."""
    items = [(_bigrams(t), 0) for t in human] + [(_bigrams(t), 1) for t in model]
    if not human or not model:
        raise ValueError("두 무리 모두 1개 이상이어야 한다")
    hits = 0
    for i, (vec, label) in enumerate(items):
        rest = [it for j, it in enumerate(items) if j != i]
        c0 = _centroid([v for v, lab in rest if lab == 0])
        c1 = _centroid([v for v, lab in rest if lab == 1])
        guess = 0 if _cosine(vec, c0) >= _cosine(vec, c1) else 1
        hits += int(guess == label)
    return hits / len(items)


def _flat(text: str) -> str:
    """시드 복제 판정용 — 공백을 모두 뺀다."""
    return "".join(text.split())


# 이 길이(공백 뺀 글자 수) 이상인 시드는 결과 파일 어디에든 **부분 문자열로** 있으면 유출로 본다.
# 더 짧은 시드("몰라" 같은 것)는 모델 발화와 우연히 겹칠 수 있어 줄 전체가 같을 때만 본다.
SEED_SUBSTRING_MIN = 6


def seed_leaks(paths: Sequence[Path], seeds: Sequence[str]) -> int:
    """결과 파일에 섞인 시드 발화 수 — 긴 시드는 부분 문자열, 짧은 시드는 표 칸 전체 일치."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in paths if p.exists())
    flat_text = _flat(text)
    cells = {_flat(c) for line in text.splitlines() for c in line.split("|")}
    count = 0
    for s in seeds:
        f = _flat(s)
        if (len(f) >= SEED_SUBSTRING_MIN and f in flat_text) or f in cells:
            count += 1
    return count


# ── 모델 1개 돌리기 ─────────────────────────────────────────────────────────


async def run_model(model: str, seeds: Sequence[str]) -> dict[str, object]:
    """모델 1개 × LLM 페르소나 4 × 문항 5 → 위반 수·구분 정확도·시드 복제 수 + 샘플 발화."""
    # 첫 호출은 모델을 메모리에 올리느라 느리다 — 클라이언트 제한 시간을 60초로 맞춘다
    provider = FixedModelOllamaProvider(model, timeout=student.STUDENT_LLM_TIMEOUT_S)
    seed_flat = {_flat(s) for s in seeds}
    violations: dict[str, int] = {}
    details: dict[str, list[list[str]]] = {}
    lines_by_persona: dict[str, list[str]] = {}
    all_lines: list[str] = []
    copies = 0
    for persona in sorted(student.LLM_PERSONAS):
        per: list[list[str]] = []
        lines: list[str] = []
        for pid in COMPARE_PROBLEMS:
            problem = _problem(pid)
            forced = demo_wrong_answer(problem) if persona == "P3" else None
            prompt = student.build_prompt(persona, problem, [], forced, seeds)
            student.check_prompt_privacy(prompt, identifiers=(), answer=problem["answer"])
            # 시드가 실린 프롬프트는 student._call_local_ollama(로컬 결정 확인 포함)로만 보낸다
            raw = await student._call_local_ollama(  # noqa: SLF001 — 같은 sim 패키지
                prompt, provider, seed=student._stable(f"{model}:{persona}:{pid}")  # noqa: SLF001
            )
            raw_lines = [ln for ln in raw.splitlines() if ln.strip()]
            line = student.clean_line(raw)
            per.append(rule_violations(persona, line, len(raw_lines), forced))
            if _flat(line) in seed_flat:
                copies += 1
                line = SEED_COPY_MASK
            lines.append(line)
            all_lines.append(line)
        violations[persona] = sum(1 for v in per if v)
        details[persona] = per
        lines_by_persona[persona] = lines
    model_lines = [ln for ln in all_lines if ln != SEED_COPY_MASK]
    accuracy = discrimination_accuracy(seeds, model_lines) if model_lines else 1.0
    return {
        "model": model,
        "violations_by_persona": violations,
        "violations_total": sum(violations.values()),
        "violation_kinds": dict(Counter(k for per in details.values() for v in per for k in v)),
        "discrimination_accuracy": round(accuracy, 3),
        "seed_copies": copies,
        "utterances": len(all_lines),
        "_lines": lines_by_persona,
    }


def choose(results: Sequence[dict[str, object]]) -> str:
    """고르는 규칙 — 위반 적은 쪽 → 구분 정확도 낮은 쪽 → 시드 복제 적은 쪽."""

    def key(r: dict[str, object]) -> tuple[float, float, float]:
        return (
            float(str(r["violations_total"])),
            float(str(r["discrimination_accuracy"])),
            float(str(r["seed_copies"])),
        )

    return str(min(results, key=key)["model"])


# ── 샘플 문서 ─────────────────────────────────────────────────────────────


def _rule_samples() -> dict[str, list[str]]:
    """규칙 페르소나 4종 × 문항 5개의 첫 입력(P8은 주입기 답 없이 = 아무 숫자)."""
    out: dict[str, list[str]] = {}
    for persona in sorted(student.RULE_PERSONAS):
        out[persona] = [
            student.rule_reply(persona, _problem(pid), [], None) for pid in SAMPLE_PROBLEMS
        ]
    return out


def _fake_llm_samples() -> dict[str, list[str]]:
    """가짜 모드 대본 4종 × 문항 5개의 첫 입력(P2·P3은 비교용 고정 오답을 주입기 답으로)."""
    out: dict[str, list[str]] = {}
    for persona in sorted(student.LLM_PERSONAS):
        lines = []
        for pid in SAMPLE_PROBLEMS:
            problem = _problem(pid)
            forced = demo_wrong_answer(problem) if persona in ("P2", "P3") else None
            lines.append(student.fake_llm_reply(persona, problem, [], forced))
        out[persona] = lines
    return out


def _show(line: str) -> str:
    """샘플 표에 넣을 꼴 — 빈 입력·긴 붙여넣기는 설명으로, 표를 깨는 `|`는 이스케이프."""
    if line == "":
        return "(빈 입력)"
    if len(line) > student.MAX_REPLY_LEN:
        return f"(붙여넣기 {len(line)}자 · 앞 40자) {line[:40]}…".replace("|", "\\|")
    return line.replace("|", "\\|")


def render_samples(
    rule: dict[str, list[str]], llm: dict[str, list[str]], llm_source: str, problems: Sequence[str]
) -> str:
    """samples.md 본문 — 페르소나별 발화 5개(모델 출력만 · 시드 원문 없음)."""
    head = [
        "# S18 학생 시뮬레이터 발화 샘플 (페르소나 8개 × 5)",
        "",
        "> 시드 원문은 넣지 않는다 — 규칙 페르소나 출력과 로컬 모델(또는 가짜 대본) 출력만.",
        f"> 로컬 Ollama 페르소나(P2·P3·P4·P6) 출처: {llm_source}",
        "> 모두 그 문항의 **첫 입력**이다. P3(와 샘플의 P2)의 주입기 답은 비교용 고정 오답"
        "(`student_compare.demo_wrong_answer` — 수는 부호 반대 · 식은 기울기·절편 뒤바꿈)이다.",
        "",
        "| 페르소나 | " + " | ".join(problems) + " |",
        "| --- | " + " | ".join("---" for _ in problems) + " |",
    ]
    rows = []
    for persona in student.PERSONAS:
        lines = rule.get(persona) or llm.get(persona) or []
        label = f"{persona} {student.PERSONAS[persona]}"
        rows.append(f"| {label} | " + " | ".join(_show(x) for x in lines) + " |")
    return "\n".join(head + rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    """명령줄 진입점. 숫자만 찍는다(발화 원문·시드 원문은 화면에 없다)."""
    parser = argparse.ArgumentParser(description="학생 모델 후보 비교(S18)")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--fake", action="store_true", help="Ollama 없이 가짜 대본 samples.md만")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.fake:
        text = render_samples(
            _rule_samples(),
            _fake_llm_samples(),
            "**가짜 모드 대본**(GOLDEN_FAKE_LLM=1 · 로컬 모델 미호출) — "
            "Kiki 머신 비교 실행이 이 파일을 덮어쓴다",
            SAMPLE_PROBLEMS,
        )
        (args.out / "samples.md").write_text(text, encoding="utf-8")
        print(f"SAMPLES_WRITTEN=fake path={args.out / 'samples.md'}")
        return 0

    if os.environ.get("GOLDEN_FAKE_LLM") == "1":
        print("COMPARE_REFUSED=True — GOLDEN_FAKE_LLM=1이 켜져 있다(실제 모델 비교 불가)")
        return 2
    try:
        seeds = student.load_seed_utterances()
    except student.SeedFileMissingError as exc:
        print(f"COMPARE_REFUSED=True — {exc}", file=sys.stderr)
        return 2
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results: list[dict[str, object]] = []
    for model in models:
        try:
            results.append(asyncio.run(run_model(model, seeds)))
        except (student.StudentSimError, OSError, httpx.HTTPError) as exc:  # 기록하고 다음 모델로
            print(f"MODEL_FAILED model={model} error={type(exc).__name__}", file=sys.stderr)
    if not results:
        print("COMPARE_FAILED=True — 돌아간 모델이 0개다", file=sys.stderr)
        return 1
    chosen = choose(results)
    public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    summary = {
        "models_requested": models,
        "models_ran": [r["model"] for r in results],
        "compare_problems": list(COMPARE_PROBLEMS),
        "comparison": "실시" if len(results) >= 2 else "미실시(모델 1개만 돌았다)",
        "chosen": chosen,
        "results": public,
    }
    (args.out / "model_compare.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    best = next(r for r in results if r["model"] == chosen)
    lines = best["_lines"]
    assert isinstance(lines, dict)
    text = render_samples(
        _rule_samples(),
        {k: list(v) for k, v in lines.items()},
        f"로컬 Ollama `{chosen}`(비교에서 고른 모델 · 문항 {', '.join(COMPARE_PROBLEMS)})",
        COMPARE_PROBLEMS,
    )
    (args.out / "samples.md").write_text(text, encoding="utf-8")
    leaked = seed_leaks([args.out / "samples.md", args.out / "model_compare.json"], seeds)
    if leaked:
        # 시드 원문이 결과 파일에 섞였다 — 파일을 지우고 멈춘다(밀어 올릴 것이 남지 않게)
        for path in (args.out / "samples.md", args.out / "model_compare.json"):
            path.unlink(missing_ok=True)
        print(
            f"COMPARE_REFUSED=True — 결과 파일에 시드 발화 {leaked}건이 섞여 지웠다",
            file=sys.stderr,
        )
        return 3
    for r in public:
        print(
            f"MODEL={r['model']} VIOLATIONS={r['violations_total']} "
            f"BY_PERSONA={json.dumps(r['violations_by_persona'], ensure_ascii=False)} "
            f"DISCRIM_ACC={r['discrimination_accuracy']} SEED_COPIES={r['seed_copies']}"
        )
    print(f"CHOSEN={chosen} COMPARISON={summary['comparison']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
