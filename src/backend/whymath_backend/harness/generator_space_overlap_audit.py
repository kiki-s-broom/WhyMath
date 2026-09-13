"""형제 생성기 **파라미터 공간 겹침** 전수 감사 — QUAL-08.

무엇을 재는가 (그리고 `problem_duplication_audit`과 무엇이 다른가)
------------------------------------------------------------------
`problem_duplication_audit`은 **코퍼스**(이미 적재된 JSONL)를 읽어 중복을 센다. 이 모듈은 그
한 단계 위, **생성기 자신의 공간**을 잰다. 둘은 대체재가 아니다 —

  · 코퍼스는 공간의 *표본*이다. 배치는 `n`으로 잘라 적재하므로(예: 고교 몫미분 배치 n=200,
    풀 300) 코퍼스가 깨끗해도 공간이 겹쳐 있으면 **재생성·증량 시 그대로 재발**한다.
  · QUAL-07이 정확히 그 형태였다: 고교 몫미분 생성기가 대학 CALC1 생성기의 설계를 "그대로
    재적용"해 계수 범위 4개가 글자 그대로 같았고(시드까지 동일), 대학 풀 260이 고교 풀 300의
    **진부분집합**이었다. 코퍼스에 드러난 71쌍은 그 구조의 그림자였다.

그래서 이 모듈은 각 생성기의 풀을 **소진할 때까지** 뽑아(`generate()`가 None을 낼 때까지)
공간 전체를 만든 뒤, 생성기 쌍마다 교집합을 구한다. 표본이 아니라 공간을 본다.

판정 축 선정 — 왜 발문 축인가 (QUAL-08 acceptance ②·실측 2026-09-13)
---------------------------------------------------------------------
후보 4축을 **같은 모집단**에 걸어 오탐(현행 트렁크 전수)과 진양성(QUAL-07 수정 직전 코드를
양성 대조군으로 재현) 양쪽을 측정했다. 정상 입력에서 조용한 것은 변별력의 증거가 아니므로
(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지") 두 열을 같이 본다:

  ┌ 축 ──────────────────┬ 현행 겹침 ────┬ 대조군(QUAL-07 직전) ─┬ 판정 ────────────────┐
  │ ① 발문(정규화 텍스트) │ 0쌍 / 1,378쌍 │ 129건 검출            │ **채택**              │
  │ ② 조건식              │ 10쌍(595 문자열)│ 260건 검출          │ 기각 — 오탐 10/10     │
  │ ③ 조건식+단원코드     │ 0쌍           │ **0건 — 놓침**        │ 기각 — 변별력 0       │
  │ ④ 생성 파라미터 튜플  │ 측정 불가     │ 측정 불가             │ 기각 — 비교 불가      │
  └───────────────────────┴───────────────┴───────────────────────┴───────────────────────┘

②는 민감하지만 오탐이 지배한다 — 공유 조건식 10쌍을 발문까지 열어 판정한 결과 **10쌍 전부**가
수학적으로 무관하거나 교수학적으로 다른 문항이었다(대표 예: 복소수 실수부 합 `(-1) + (-3) = y`
가 다항식 상수항 합과 같다 / 삼차함수 도함수 `x**2 + 10*x + 21 = 0`이 이차방정식 근 문제와
같다 / `1km² = 1,000,000m²`와 `1m³ = 1,000,000cm³`가 같은 `x - (1 * 1000000) = 0`을 낸다).
`problem_duplication_audit` T3가 코퍼스 축에서 같은 결론을 냈고 이 모듈이 공간 축에서 재확인
했다.

③은 ②의 오탐을 **단원코드 동시 일치**로 걸러 현행 0쌍을 낸다 — 겉보기엔 이상적이다. 그러나
양성 대조군에서 **0건**이다: QUAL-07의 두 생성기는 단원코드가 `HS-CALC2-QUOTIENT-RULE`과
`CALC1-QUOTIENT-RULE`로 달랐기 때문이다. 잡아야 할 단 하나의 실제 사고를 못 잡는 축은 모든
입력에서 초록인 가드이며 채택하면 위장이 된다. 이 축을 **버린 근거를 여기 남긴다** — 미래
세션이 "조건식은 오탐이 많으니 단원코드를 AND하자"는 자연스러운 개선을 다시 제안할 때
그것이 이미 측정으로 기각된 안임을 알 수 있게.

④는 생성기마다 스켈레톤 dataclass가 제각각이라(`_Skeleton`의 필드가 도메인별로 다르다) 쌍
사이에 비교 가능한 공통 튜플이 없다. 공통 표현으로 투영하려면 결국 발문이나 조건식으로
내려오므로 독립 축이 성립하지 않는다.

①의 오탐률이 0인 것은 우연이 아니라 **정의상**이다 — 서로 다른 생성기가 정규화 후 바이트
동일한 발문을 낸다면 그것은 "비슷한 문항"이 아니라 **같은 문항**이고, 학생이 두 단원에서
같은 문제를 두 번 만나는 것이 QUAL-07이 고친 해악 자체다. 판정과 해악이 같은 대상을 가리키는
축이라 사람이 다시 판정할 여지가 없다.

이 축이 보지 못하는 것(정직 회계)
---------------------------------
발문이 **한 글자라도** 다르면 이 축은 겹침으로 세지 않는다. 그래서 "수학 실체는 같은데 발문
형식만 다른" 쌍은 통과한다 — 실측 예: `InductiveSequenceSkeletonGenerator`(a₁=1, aₙ₊₁=2·aₙ,
a₃)와 `GeometricSequenceSkeletonGenerator`(첫째항 1·공비 2의 제3항)는 45건에서 수학 실체가
같다. 이 모듈은 그것을 겹침으로 세지 **않는다** — 점화식 해석과 일반항 적용은 서로 다른 인지
행동이고 성취기준도 다르기 때문이다. 다만 "안 나왔다"와 "안 봤다"를 구분하려고 그 수치를
리포트 §3에 **명시적으로 싣는다**.

게이트다 (`problem_duplication_audit`과 다른 점)
-----------------------------------------------
발문 공간 겹침이 1쌍이라도 나오면 **exit 1**이다. 오탐률이 0으로 측정됐고 진양성 검출이 양성
대조군으로 증명됐으므로 차단해도 사람이 게이트를 끄게 되지 않는다. 종료 코드: 0=겹침 없음 /
1=겹침 발견 / 2=입력·측정 오류(측정 실패가 "0건 통과"로 위장되지 않게 분리).

계층 메모(CLAUDE.md 7계층): L3 생성기를 *호출만* 하는 빌드타임 도구다(hermetic — DB·네트워크·
LLM 0, 고정 스펙). 생성기를 수정하지 않고 코퍼스를 읽지도 쓰지도 않는다.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pkgutil
import re
import sys
import typing
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import whymath_backend.l3.equivalent as _equivalent_pkg
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec

__all__ = [
    "GeneratorSpace",
    "OverlapPair",
    "SpaceOverlapReport",
    "audit_generator_spaces",
    "build_instances",
    "main",
    "normalize_question_text",
    "render_report",
]

# 풀 소진 상한 — 이 수를 넘겨도 None이 안 나오면 "전수 열거 실패"로 정직하게 표시한다(잘린
# 표본으로 "겹침 0"을 선언하면 그 0이 위장이 된다). 현행 최대 풀은 34,800(SampleMean 기본
# 구성: mean+variance 합산)이라 50,000은 실측 여유값이다.
_DRAIN_CAP = 50_000

# 감사 대상 모듈 접미사 — `l3/equivalent/`의 스켈레톤 생성기 규약.
_MODULE_SUFFIX = "skeleton_generator"

# 전 생성기에 같은 스펙을 준다 — 성취기준 코드는 발문에 들어가지 않고 slug에만 쓰이므로
# 공간 비교에 영향이 없다(스펙 차이가 만드는 가짜 차이를 원천 제거).
_AUDIT_SPEC = EquivalenceSpec(
    achievement_standard_codes=frozenset({"QUAL08-AUDIT"}),
    target_misconception_ids=frozenset(),
    difficulty_overall=3.0,
    answer_format=None,
)

# `Literal`이 아닌 필수 인자의 합성 채움값 — 생성기가 L4 오개념 id를 주입받는 자리라
# (하드코딩 0 원칙) 감사기가 더미를 넣는다. 발문에 나타나지 않는 값이므로 공간에 영향 없다.
_REQUIRED_ARG_FILLERS: Mapping[str, object] = {
    "distractor_codes": {
        "max_min": ("QUAL08-AUDIT-MISC", "QUAL08-AUDIT-OP"),
        "value_vs_point": ("QUAL08-AUDIT-MISC", "QUAL08-AUDIT-OP"),
        "opposite_root": ("QUAL08-AUDIT-MISC", "QUAL08-AUDIT-OP"),
        "sign_flip": ("QUAL08-AUDIT-MISC", "QUAL08-AUDIT-OP"),
    },
}

_WHITESPACE = re.compile(r"\s+")


def normalize_question_text(text: str | None) -> str:
    """발문 정규화 — NFC + 공백 연속 축약(`problem_duplication_audit`과 같은 규약)."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


@dataclass(frozen=True)
class GeneratorSpace:
    """생성기 인스턴스 하나가 낼 수 있는 문항 공간(전수 또는 잘린 표본)."""

    key: str  # "<module>.<Class>[kind=...]" — 리포트·게이트 메시지의 안정 식별자
    module: str
    cls: str
    config: str  # 필수 인자 구성(없으면 "")
    size: int
    exhausted: bool  # False면 `_DRAIN_CAP`에서 잘렸다 — "겹침 0"을 서로소로 읽으면 안 된다
    questions: frozenset[str]
    conditions: frozenset[str]


@dataclass(frozen=True)
class OverlapPair:
    """두 생성기 공간의 교집합."""

    left: str
    right: str
    shared: int
    samples: tuple[str, ...]
    both_exhausted: bool


@dataclass
class SpaceOverlapReport:
    """감사 결과 — 측정한 것과 **측정하지 못한 것**을 같이 담는다."""

    spaces: list[GeneratorSpace] = field(default_factory=list)
    unmeasured: list[tuple[str, str]] = field(default_factory=list)  # (key, 사유)
    question_overlaps: list[OverlapPair] = field(default_factory=list)
    condition_overlaps: list[OverlapPair] = field(default_factory=list)

    @property
    def pairs_compared(self) -> int:
        n = len(self.spaces)
        return n * (n - 1) // 2

    @property
    def truncated(self) -> list[GeneratorSpace]:
        return [s for s in self.spaces if not s.exhausted]

    @property
    def ok(self) -> bool:
        """게이트 판정 — 발문 공간 겹침이 하나도 없어야 통과."""
        return not self.question_overlaps


def _literal_options(annotation: object) -> tuple[object, ...] | None:
    """`Literal['a','b']`(또는 `Literal[...] | None`)이면 그 값들을, 아니면 None."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return typing.get_args(annotation)
    if origin is not None:  # Union 등 — 내부에 Literal이 있으면 그것을 쓴다
        for arg in typing.get_args(annotation):
            if typing.get_origin(arg) is typing.Literal:
                return typing.get_args(arg)
    return None


def _required_params(cls: type) -> list[inspect.Parameter]:
    """기본값이 없는 생성자 인자(self 제외)."""
    initializer: Any = getattr(cls, "__init__", None)
    try:
        sig = inspect.signature(initializer)
    except (TypeError, ValueError):
        return []
    hints: dict[str, object] = {}
    try:
        hints = typing.get_type_hints(initializer)
    except Exception:  # noqa: BLE001 — 해석 실패는 힌트 없음으로 강등(원인은 아래 사유에 남는다)
        hints = {}
    out: list[inspect.Parameter] = []
    for name, param in sig.parameters.items():
        if name == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        annotation = hints.get(name, param.annotation)
        out.append(param.replace(annotation=annotation))
    return out


def build_instances(cls: type) -> tuple[list[tuple[str, object]], str | None]:
    """클래스 하나에서 감사 대상 인스턴스들을 만든다.

    반환 `([(구성라벨, 인스턴스), ...], 실패사유)`. 필수 인자가 `Literal`이면 **모든 값으로**
    인스턴스를 만든다 — `kind`/`band`가 사실상 서로 다른 문항 공간을 가르기 때문이다(하나만
    만들면 나머지 공간을 통째로 안 본 채 "겹침 0"이 된다).
    """
    required = _required_params(cls)
    choices: list[tuple[str, list[tuple[str, object]]]] = []
    for param in required:
        options = _literal_options(param.annotation)
        if options is not None:
            choices.append((param.name, [(f"{param.name}={o!r}", o) for o in options]))
            continue
        if param.name in _REQUIRED_ARG_FILLERS:
            choices.append((param.name, [("", _REQUIRED_ARG_FILLERS[param.name])]))
            continue
        return [], (
            f"필수 인자 '{param.name}'를 감사기가 채울 수 없음" f"(annotation={param.annotation!r})"
        )

    combos: list[tuple[list[str], dict[str, object]]] = [([], {})]
    for name, labelled in choices:
        combos = [
            (labels + ([label] if label else []), {**kwargs, name: value})
            for labels, kwargs in combos
            for label, value in labelled
        ]

    built: list[tuple[str, object]] = []
    for labels, kwargs in combos:
        try:
            built.append((",".join(labels), cls(**kwargs)))
        except Exception as exc:  # noqa: BLE001 — 타입명을 사유에 남긴다(침묵 실패 금지)
            return [], f"인스턴스화 실패({','.join(labels) or '기본'}): {type(exc).__name__}: {exc}"
    return built, None


def _drain(generator: object) -> tuple[set[str], set[str], int, bool]:
    """풀이 빌 때까지(또는 상한까지) 뽑아 발문·조건식 집합을 만든다."""
    questions: set[str] = set()
    conditions: set[str] = set()
    count = 0
    while count < _DRAIN_CAP:
        candidate = generator.generate(_AUDIT_SPEC)  # type: ignore[attr-defined]
        if candidate is None:
            return questions, conditions, count, True
        count += 1
        questions.add(normalize_question_text(candidate.problem.question_text))
        raw = candidate.conditions
        conditions.add(
            normalize_question_text(
                raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True, ensure_ascii=False)
            )
        )
    return questions, conditions, count, False


def _generator_classes() -> Iterator[tuple[str, str, type]]:
    """`l3/equivalent/`의 스켈레톤 생성기 클래스를 이름순으로 낸다."""
    for module_info in sorted(pkgutil.iter_modules(_equivalent_pkg.__path__), key=lambda m: m.name):
        if not module_info.name.endswith(_MODULE_SUFFIX):
            continue
        module = importlib.import_module(f"{_equivalent_pkg.__name__}.{module_info.name}")
        for name, obj in sorted(vars(module).items()):
            if not inspect.isclass(obj) or obj.__module__ != module.__name__:
                continue
            if not callable(getattr(obj, "generate", None)):
                continue
            yield module_info.name, name, obj


def _pair_overlaps(
    spaces: Sequence[GeneratorSpace], attr: str, sample_limit: int = 3
) -> list[OverlapPair]:
    pairs: list[OverlapPair] = []
    for index, left in enumerate(spaces):
        for right in spaces[index + 1 :]:
            shared = getattr(left, attr) & getattr(right, attr)
            if not shared:
                continue
            pairs.append(
                OverlapPair(
                    left=left.key,
                    right=right.key,
                    shared=len(shared),
                    samples=tuple(sorted(shared)[:sample_limit]),
                    both_exhausted=left.exhausted and right.exhausted,
                )
            )
    return sorted(pairs, key=lambda p: (-p.shared, p.left, p.right))


def audit_generator_spaces() -> SpaceOverlapReport:
    """전 생성기 공간을 만들어 쌍별 겹침을 판정한다."""
    report = SpaceOverlapReport()
    for module_name, class_name, cls in _generator_classes():
        instances, failure = build_instances(cls)
        if failure is not None:
            report.unmeasured.append((f"{module_name}.{class_name}", failure))
            continue
        for config, generator in instances:
            key = f"{module_name}.{class_name}" + (f"[{config}]" if config else "")
            try:
                questions, conditions, size, exhausted = _drain(generator)
            except Exception as exc:  # noqa: BLE001 — 예외 타입명 필수(침묵 실패 금지)
                report.unmeasured.append((key, f"생성 중 예외: {type(exc).__name__}: {exc}"))
                continue
            report.spaces.append(
                GeneratorSpace(
                    key=key,
                    module=module_name,
                    cls=class_name,
                    config=config,
                    size=size,
                    exhausted=exhausted,
                    questions=frozenset(questions),
                    conditions=frozenset(conditions),
                )
            )
    report.spaces.sort(key=lambda s: s.key)
    report.question_overlaps = _pair_overlaps(report.spaces, "questions")
    report.condition_overlaps = _pair_overlaps(report.spaces, "conditions")
    return report


def render_report(report: SpaceOverlapReport) -> str:
    """사람이 읽는 리포트 — 판정·근거·측정하지 못한 범위를 같이 낸다."""
    lines: list[str] = []
    lines.append("# 형제 생성기 파라미터 공간 겹침 감사 (QUAL-08)")
    lines.append("")
    lines.append("## 1. 모집단 — 무엇을 재고 무엇을 못 쟀는가")
    total_candidates = sum(s.size for s in report.spaces)
    lines.append(
        f"- 감사한 생성기 구성 **{len(report.spaces)}개** "
        f"(전수 열거 문항 {total_candidates:,}건 · 비교한 쌍 {report.pairs_compared:,}쌍)"
    )
    truncated = report.truncated
    lines.append(
        f"- 풀 소진 실패(상한 {_DRAIN_CAP:,}에서 잘림) **{len(truncated)}개** — "
        "이 구성의 '겹침 0'은 서로소가 아니라 *표본에서 안 나왔다*는 뜻이다"
    )
    for space in truncated:
        lines.append(f"    · {space.key}")
    lines.append(f"- 측정하지 못한 클래스 **{len(report.unmeasured)}개**")
    for key, reason in report.unmeasured:
        lines.append(f"    · {key} — {reason}")
    lines.append("")
    lines.append("## 2. 판정 축(발문 공간 교집합) — 게이트")
    if not report.question_overlaps:
        lines.append(
            f"- **겹침 0쌍** / 비교 {report.pairs_compared:,}쌍. "
            "서로 다른 생성기가 같은 발문을 낼 수 있는 구성은 없다."
        )
    else:
        lines.append(
            f"- **겹침 {len(report.question_overlaps)}쌍** — 처분 필요"
            "(QUAL-07 선례: 문항 은퇴가 아니라 생성기 공간 분리)."
        )
        for pair in report.question_overlaps:
            lines.append(f"    · [{pair.shared}건] {pair.left}  ×  {pair.right}")
            for sample in pair.samples:
                lines.append(f"        예: {sample[:160]}")
    lines.append("")
    lines.append("## 3. 진단 축(조건식 교집합) — 판정에 쓰지 않는다")
    lines.append(
        "- 조건식 동일은 오탐이 지배한다(모듈 docstring 축 비교표 참고). 아래는 *참고 수치*이며 "
        "게이트가 아니다 — 이 축으로 exit 1을 내지 않는다."
    )
    lines.append(f"- 조건식을 공유하는 생성기 쌍 **{len(report.condition_overlaps)}쌍**")
    for pair in report.condition_overlaps:
        lines.append(f"    · [{pair.shared}건] {pair.left}  ×  {pair.right}")
    lines.append("")
    lines.append("## 4. 판정")
    verdict = "✅ 발문 공간 겹침 없음 (exit 0)" if report.ok else "❌ 발문 공간 겹침 발견 (exit 1)"
    lines.append(f"- {verdict}")
    return "\n".join(lines)


def _report_payload(report: SpaceOverlapReport) -> dict[str, object]:
    return {
        "measured_configs": len(report.spaces),
        "pairs_compared": report.pairs_compared,
        "total_candidates": sum(s.size for s in report.spaces),
        "truncated": [s.key for s in report.truncated],
        "unmeasured": [{"key": k, "reason": r} for k, r in report.unmeasured],
        "question_overlaps": [
            {"left": p.left, "right": p.right, "shared": p.shared, "samples": list(p.samples)}
            for p in report.question_overlaps
        ],
        "condition_overlaps": [
            {"left": p.left, "right": p.right, "shared": p.shared}
            for p in report.condition_overlaps
        ],
        "ok": report.ok,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generator_space_overlap_audit",
        description="형제 생성기 파라미터 공간 겹침 감사(QUAL-08) — 발문 공간 교집합 게이트.",
    )
    parser.add_argument("--json", dest="json_path", default=None, help="리포트 JSON 저장 경로")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = audit_generator_spaces()
    except Exception as exc:  # noqa: BLE001 — 측정 실패를 "0건 통과"로 위장하지 않는다
        print(f"❌ 측정 실패 — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(render_report(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(_report_payload(report), handle, ensure_ascii=False, indent=2)
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
