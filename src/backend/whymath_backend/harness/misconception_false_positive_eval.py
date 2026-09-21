"""올바른 수학 산문에 나가는 확신 오진단 측정 — 정답 해설 코퍼스 기준 (MISC-27).

설계 정본: `MISC-27` acceptance②③④. 발단은 `MISC-25` 세션의 교수학 검토가 곁가지로 낸
실측이다 — 이 저장소가 **스스로 생성한 정답 해설**에 오개념 진단이 확신 수준으로 나간다.

────────────────────────────────────────────────────────────────────────────
무엇을 재는가 — 그리고 무엇을 재지 *않는가*
────────────────────────────────────────────────────────────────────────────
`data/corpus/**/problems.jsonl`의 `answer_explanation`은 **올바른 수학 산문**이다. 그 위에서
`diagnose()` + `apply_match_quality_gate()`가 후보를 내면, 그것은 정의상 오진단이다 —
"맞게 쓴 글에 틀렸다고 말한다"는 뜻이고 의사결정 우선순위 #1(학생 안전·정서)에 직접 닿는다.

**정직한 한계 — 이것은 대리 지표다.** 정답 해설은 학생 입력이 아니다. 학생 손글씨 코퍼스가
저장소에 없으므로, "학생이 올바르게 쓴 글에 오진단이 얼마나 나가는가"를 직접 잴 수 없어
가장 가까운 올바른 산문으로 대신한다. 방향은 유효하되 절대값을 학생 지표로 인용하면 안 된다.

또한 해설 중 일부는 **오개념을 교육적으로 언급**한다("순서를 뒤집어 …로 하면 틀린다").
그런 문장에 그 오개념이 매치되는 것은 신호 정밀도 문제라기보다 *글의 성격* 문제다 —
분류에서 `정정어휘 있음` 표식으로 갈라 낸다. 갈라 두지 않으면 서로 다른 두 결함이 한
숫자에 섞여, 어느 쪽을 고쳐야 하는지가 사라진다.

────────────────────────────────────────────────────────────────────────────
왜 게이트 임계를 기본으로 걸지 않는가
────────────────────────────────────────────────────────────────────────────
착지 시점 실측이 **497/7,644(6.5%)**다. 0이 아니다. 여기에 임계를 걸면 CI가 상시 red가 되고,
상시 red인 게이트는 사람이 게이트를 끄게 만든다(CLAUDE.md "상시 실패하는 fail-open 보호").
그래서 기본은 **관측**이고, `--max-fp-ratio`는 명시할 때만 판정한다. 수치가 내려가면 그때
현재값 바로 위로 ratchet을 걸어 회귀만 막는 것이 이 도구의 의도된 사용법이다.

*수치 이력*: MISC-25 착지 **전** 885건(11.6%) → 착지 후 **497건(6.5%)**. 그 388건은
명시적 정정 언급 축(`has_explicit_correction_near_signals`)이 걷어 낸 몫이다 — 재측정 없이
885를 인용하면 이미 고쳐진 몫을 중복 계상한다(acceptance② 요구).

사용:
    python -m whymath_backend.harness.misconception_false_positive_eval
    python -m whymath_backend.harness.misconception_false_positive_eval --max-fp-ratio 0.07
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID, EXPLICIT_CORRECTION_MENTION
from whymath_backend.l4.misconception.diagnose import _normalize, diagnose
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate

__all__ = [
    "FalsePositive",
    "FalsePositiveReport",
    "classify_cause",
    "evaluate",
    "format_report",
    "load_answer_explanations",
    "main",
    "weak_signal_gap",
]

_EXIT_OK = 0
_EXIT_FAIL = 1
# 잰 것이 없으면 기준 미달이 아니라 측정 실패다(모집단 0 = 통과 위장 금지).
_EXIT_UNMEASURABLE = 2

_CORRECTION = re.compile(EXPLICIT_CORRECTION_MENTION)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def load_answer_explanations() -> list[str]:
    """코퍼스의 `answer_explanation`을 중복 제거해 정렬 반환(결정론·DB 0·네트워크 0).

    중복을 제거하는 이유: 같은 해설 템플릿이 문항 수만큼 반복되므로, 제거하지 않으면
    템플릿 1건의 결함이 수백 건으로 계상돼 비율이 생성기 물량에 좌우된다.
    """
    seen: set[str] = set()
    for path in sorted((_repo_root() / "data" / "corpus").glob("problem_bank_*/problems.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = record.get("answer_explanation")
            if isinstance(text, str) and text.strip():
                seen.add(text.strip())
    return sorted(seen)


def _is_weak(signal: str) -> bool:
    """숫자-only·단일 ASCII 문자 signal — 다른 주장 안에서 정당하게 등장하는 약한 토큰."""
    norm = _normalize(signal)
    return norm.isdigit() or (len(norm) == 1 and norm.isascii() and norm.isalpha())


def weak_signal_gap(kebab_id: str, text: str) -> int | None:
    """약한 signal이 **가장 가까운 내용성 signal**과 떨어진 거리(정규형 문자·최댓값).

    약한 신호가 여럿이면 그중 가장 나쁜(먼) 것을 쓴다 — "모든 약한 신호가 가까울 것"을
    요구하는 판정과 눈금을 맞추기 위해서다. 어느 쪽도 없으면 `None`(해당 없음).

    ────────────────────────────────────────────────────────────────────────
    이 함수는 **기각된 가설의 재현 장치**다 (MISC-29)
    ────────────────────────────────────────────────────────────────────────
    `MISC-29`는 "약한 signal은 내용성 signal에서 N자 이내일 때만 센다"는 근접 요구로
    `weak-signal` 계열 오진단을 걷어 내려 했다. 전수 측정이 그 설계를 **기각했다**:

        순수 오탐(정정 언급 없음·22건) 거리 : 12 · 27 · 29
        진짜 오개념 발화 거리               : 0 · 1 · 3 · 10 · **13**

    거리 13짜리 정탐이 거리 12짜리 오탐보다 **멀다**. 그 정탐은
    `"분모에 변수가 와도 항상 정의되니까 0을 넣어도 된다"` — `division-by-zero`의
    `canonical_statement`를 학생이 그대로 발화한 형태라 반드시 잡아야 하는 문장이다.
    두 분포가 겹치므로 단일 거리 임계로는 가를 수 없다.

    함수를 남기는 이유는 그 판정을 **재현 가능하게** 하기 위해서다 — 지우면 다음 세션이
    같은 가설을 처음부터 다시 세우고 같은 측정을 반복한다. 리포트가 분포를 함께 내므로
    코퍼스가 바뀌어 겹침이 해소되면 그때 다시 검토할 수 있다.
    """
    misconception = CATALOG_BY_ID[kebab_id]
    norm = _normalize(text)
    weak = [s for s in misconception.signals if _is_weak(s)]
    strong = [s for s in misconception.signals if not _is_weak(s)]
    if not weak or not strong:
        return None
    worst = 0
    for weak_signal in weak:
        norm_weak = _normalize(weak_signal)
        occurrences = [i for i in range(len(norm)) if norm.startswith(norm_weak, i)]
        if not occurrences:
            return None
        nearest: int | None = None
        for weak_at in occurrences:
            for strong_signal in strong:
                norm_strong = _normalize(strong_signal)
                strong_at = norm.find(norm_strong)
                if strong_at < 0:
                    continue
                gap = max(
                    0,
                    max(weak_at, strong_at)
                    - min(weak_at + len(norm_weak), strong_at + len(norm_strong)),
                )
                nearest = gap if nearest is None else min(nearest, gap)
        if nearest is None:
            return None
        worst = max(worst, nearest)
    return worst


@dataclass(frozen=True)
class FalsePositive:
    """올바른 산문 1건에 나간 top-1 오진단."""

    kebab_id: str
    confidence: float
    matched_signals: tuple[str, ...]
    mentions_correction: bool
    text: str

    @property
    def cause(self) -> str:
        return classify_cause(self)


def classify_cause(item: FalsePositive) -> str:
    """원인 유형 — 고칠 자리가 서로 다르므로 한 숫자에 섞지 않는다(acceptance③)."""
    misconception = CATALOG_BY_ID[item.kebab_id]
    if not item.matched_signals:
        base = "regex-only"  # substring 0 — 정규식 채널이 단독으로 확신을 만들었다
    elif all(_is_weak(s) for s in item.matched_signals):
        base = "weak-signals-only"  # 숫자·단일문자만으로 full match
    elif any(_is_weak(s) for s in item.matched_signals):
        base = "weak-signal-mixed"  # 약한 토큰이 끼어 full match를 완성
    elif len(misconception.signals) <= 2:
        base = "two-signal-cooccurrence"  # 내용성이지만 신호 2개라 우연 공출현이 쉽다
    else:
        base = "other"
    # 해설이 그 오개념을 *가르치려고* 언급한 경우와 순수 오탐을 갈라 둔다.
    return f"{base}+correction-mention" if item.mentions_correction else base


@dataclass(frozen=True)
class FalsePositiveReport:
    total: int
    false_positives: tuple[FalsePositive, ...]

    @property
    def fp_ratio(self) -> float | None:
        """모집단이 0이면 0.0이 아니라 `None` — 분모 없는 0 금지."""
        return None if not self.total else len(self.false_positives) / self.total

    @property
    def by_cause(self) -> Counter[str]:
        return Counter(fp.cause for fp in self.false_positives)

    @property
    def by_misconception(self) -> Counter[str]:
        return Counter(fp.kebab_id for fp in self.false_positives)

    def to_json(self) -> dict[str, object]:
        return {
            "total_explanations": self.total,
            "false_positives": len(self.false_positives),
            "fp_ratio": self.fp_ratio,
            "by_cause": dict(self.by_cause),
            "by_misconception": dict(self.by_misconception.most_common()),
        }


def evaluate(explanations: list[str] | None = None) -> FalsePositiveReport:
    texts = load_answer_explanations() if explanations is None else explanations
    found: list[FalsePositive] = []
    for text in texts:
        gated = apply_match_quality_gate(diagnose(text, top_k=len(CATALOG_BY_ID)))
        if not gated.matches:
            continue
        # top-1만 센다 — 학생에게 실제로 나가는 것이 그것이다.
        match = gated.matches[0]
        found.append(
            FalsePositive(
                kebab_id=match.misconception.id,
                confidence=match.confidence,
                matched_signals=match.matched_signals,
                mentions_correction=bool(_CORRECTION.search(_normalize(text))),
                text=text,
            )
        )
    return FalsePositiveReport(total=len(texts), false_positives=tuple(found))


def format_report(report: FalsePositiveReport, *, top_n: int = 10) -> str:
    lines = [
        "=" * 72,
        "올바른 산문에 나가는 확신 오진단 — 정답 해설 코퍼스 기준 (MISC-27)",
        "=" * 72,
        f"  모집단(중복 제거 해설) : {report.total}건",
    ]
    ratio = report.fp_ratio
    if ratio is None:
        lines.append("  오진단                : 측정 불가 — 모집단 0건(통과 아님)")
    else:
        lines.append(f"  오진단                : {len(report.false_positives)}건 ({ratio:.1%})")
    if report.false_positives:
        lines += ["", "  [원인별] 고칠 자리가 다르므로 섞지 않는다:"]
        for cause, n in report.by_cause.most_common():
            lines.append(f"    {n:>5}건  {cause}")
        lines += ["", f"  [오개념별 상위 {top_n}]:"]
        for kebab, n in report.by_misconception.most_common(top_n):
            signals = CATALOG_BY_ID[kebab].signals
            lines.append(f"    {n:>5}건  {kebab:<40} signals={signals}")

        # MISC-29 기각 근거의 재현 — 약한 신호 거리 분포를 함께 낸다.
        gaps = Counter(
            gap
            for fp in report.false_positives
            if (gap := weak_signal_gap(fp.kebab_id, fp.text)) is not None
        )
        if gaps:
            spread = " ".join(f"{g}:{n}" for g, n in sorted(gaps.items()))
            lines += [
                "",
                "  [약한 신호 거리 분포] 거리:건수 — MISC-29가 근접 임계를 기각한 근거:",
                f"    {spread}",
                "    진짜 오개념 발화의 거리는 0~13이라 순수 오탐(12·27·29)과 **겹친다**.",
                "    단일 거리 임계로는 못 가른다(`weak_signal_gap` docstring).",
            ]
    lines += [
        "",
        "  ※ 대리 지표다 — 정답 해설은 학생 입력이 아니다(모듈 docstring).",
        "=" * 72,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.misconception_false_positive_eval",
        description=(
            "정답 해설 코퍼스에 오개념 진단이 서빙 게이트를 넘어 나가는 비율을 재고 "
            "원인별로 나눈다(MISC-27 · hermetic·DB 0·LLM 0)."
        ),
    )
    parser.add_argument(
        "--max-fp-ratio",
        type=float,
        default=None,
        help=(
            "오진단 비율 상한 — 초과하면 exit 1. 기본 미지정=관측만. "
            "착지 시점 실측이 6.5%%라 기본 게이트를 걸면 상시 red가 된다."
        ),
    )
    parser.add_argument("--json", dest="json_path", type=Path, default=None)
    args = parser.parse_args(argv)

    report = evaluate()
    print(format_report(report))

    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"JSON 산출물: {args.json_path}")

    ratio = report.fp_ratio
    if ratio is None:
        print("[측정 불가] 해설 모집단이 0건 — 코퍼스·로더가 깨졌다(통과 아님).", file=sys.stderr)
        return _EXIT_UNMEASURABLE
    if args.max_fp_ratio is not None and ratio > args.max_fp_ratio:
        print(
            f"[게이트 미달] 오진단 비율 {ratio:.1%} > 상한 {args.max_fp_ratio:.1%}",
            file=sys.stderr,
        )
        return _EXIT_FAIL
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
