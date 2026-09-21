"""명시적 정정 언급 사각 측정 — 학생이 오개념을 *부정*했는데도 확신 진단이 나가는가 (MISC-25).

설계 정본: `MISC-25` acceptance②. 발단은 `MISC-22`(PR #1071) Codex P1 리뷰다 — 그 PR은
자신이 새로 노출시킨 5개 정규식 채널만 `EXPLICIT_CORRECTION_MENTION` 전방탐색으로 막았고,
그보다 앞서 있던 **substring 경로의 같은 사각**은 범위 밖으로 분리됐다. 이 모듈이 그 사각의
크기를 잰다.

────────────────────────────────────────────────────────────────────────────
무엇이 사각인가
────────────────────────────────────────────────────────────────────────────
`_match_one`의 `signals`는 *공출현(AND)*만 본다. 그래서 오개념을 **저지른** 풀이와 그것을
**인용해 부정한** 풀이를 구별하지 못한다. 실측:

    diagnose("x²=2x 양변을 x로 나누면 x=2라는 풀이는 틀렸다")
      → root-loss-by-dividing  confidence 1.0  (서빙 게이트 0.65 통과)

학생이 "틀렸다"고 명시했는데 그 오개념을 가졌다고 확신 개입이 나간다. 의사결정 우선순위 #1
(학생 안전·웰빙)에 직접 닿는다 — 맞게 안 학생에게 틀렸다고 말하는 쪽이 놓치는 쪽보다 해롭다
(`models.py::refuting_regex` docstring이 이미 그렇게 선언한다).

────────────────────────────────────────────────────────────────────────────
측정 설계 — 대조군이 없으면 이 측정은 위장이다
────────────────────────────────────────────────────────────────────────────
"정정 문장에서 진단이 안 나왔다"는 두 가지를 뜻할 수 있다:
  ① 반박 축이 작동했다 (우리가 재려는 것)
  ② 애초에 그 문장이 이 항목을 발화시키지 못했다 (측정 실패)
구별하지 않으면 ②가 ①로 위장한다. 그래서 항목마다 **대조군**(정정 어구 없는 같은 문장)을
함께 돌리고, 대조군이 서빙 게이트를 못 넘는 항목은 분모에서 빼고 *사유를 적어* 보고한다.

*측정 실패의 사유를 나눠 세는 이유*(1차 시도의 실제 결함): 초안 생성기는 문장에
`canonical_statement`를 붙였는데, `root-loss-by-dividing`의 그것이 `x=0 근 손실`이라
항목 자신의 `refuting_regex`(`ZERO_ROOT_MENTION`)를 밟아 **대조군이 스스로 반박**됐다.
그 결과가 "미발화"로 뭉뚱그려져 사각 1건이 통계에서 사라질 뻔했다 — 원인을 안 나누면
도구 결함이 관측 결과로 보인다(CLAUDE.md "측정·수집 도구를 성공 경로만 보고 설계 금지").

────────────────────────────────────────────────────────────────────────────
왜 confidence가 아니라 **서빙 게이트 통과**를 세는가
────────────────────────────────────────────────────────────────────────────
`apply_match_quality_gate`는 top-1 floor라 confidence가 높아도 다른 후보에 밀리면 학생에게
안 나간다. 해가 되는 것은 *confidence 수치*가 아니라 *도달*이므로 도달을 센다
(`anchor_detection_channel_eval._survives_serving_gate`와 같은 이유·같은 방식).

────────────────────────────────────────────────────────────────────────────
세 축 — 한쪽만 보면 반드시 오독한다 (MISC-28)
────────────────────────────────────────────────────────────────────────────
① **사각**(원래 축) — 학생이 부정했는데 진단이 도달하는가. 낮을수록 좋다.
② **오억제**(MISC-28 ④) — *다른 것*을 정정했는데 이 오개념까지 억제되는가. 낮을수록 좋다.
   ①만 보면 **과잉 억제가 개선으로 보인다**(무엇이든 억제하면 ①은 0%가 된다). 실제로 그
   상태였다 — ①이 0%인 동안 ②는 **100%**였고 그 사실이 어느 화면에도 없었다.
③ **보류**(MISC-28 ⓒ) — 전치 정정 라벨에서 **확신 진단이 새는가**. 0이어야 한다.
   Kiki 판정(2026-09-12)으로 전치 정정은 *억제*가 아니라 *보류*가 됐다. 그러면 ①이 그
   형태를 더는 0%로 보증하지 않는다(도달하기 때문이다). 보증해야 하는 것이 "도달하지
   않는다"에서 "도달하되 확신을 보류한다"로 바뀌었으므로 축을 하나 더 둔다 — 없으면
   ⓒ 도입이 "②가 100%→3%"라는 좋은 숫자만 남기고 그 대가를 감춘다.

사용:
    python -m whymath_backend.harness.explicit_correction_gap_eval
    python -m whymath_backend.harness.explicit_correction_gap_eval --max-gap-ratio 0.0
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l4.misconception.catalog import CATALOG, CATALOG_BY_ID
from whymath_backend.l4.misconception.diagnose import diagnose, is_refuted
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate
from whymath_backend.l4.misconception.models import Misconception

__all__ = [
    "CORRECTION_PHRASES",
    "FOREIGN_CORRECTION_PREFIXES",
    "PREFIX_CORRECTION_LABELS",
    "CorrectionProbe",
    "GapReport",
    "HeldVerdictResult",
    "ProbeResult",
    "build_probes",
    "evaluate",
    "format_report",
    "main",
    "measure_held_verdicts",
    "measure_over_suppression",
]

_EXIT_OK = 0
_EXIT_FAIL = 1
# 측정 자체가 불가한 상태(대상 0건 등)는 기준 미달과 다르다 — 통과로 위장하지 않는다.
_EXIT_UNMEASURABLE = 2

#: 학생이 오개념을 명시적으로 부정할 때 쓰는 대표 어구.
#:
#: `catalog.EXPLICIT_CORRECTION_MENTION`이 겨냥하는 표현에서 뽑았고, 활용형을 골고루 밟도록
#: 골랐다(`틀렸`·`잘못`·`오답`·`아니`). 한글 활용형은 substring 분해가 안 되므로(`틀리`가
#: `틀린`을 포함하지 않는다) 어간 하나로 대표시키면 그 축을 안 밟는다 — 카탈로그 상수의
#: 활용형 나열과 같은 이유다.
CORRECTION_PHRASES: tuple[str, ...] = (
    "라는 풀이는 틀렸다",
    "는 잘못된 계산이다",
    "로 보면 오답이다",
    "은 아니다",
)


@dataclass(frozen=True)
class CorrectionProbe:
    """항목 1개의 대조군 + 정정 변형 묶음."""

    kebab_id: str
    control: str
    refuted: tuple[str, ...]


@dataclass(frozen=True)
class ProbeResult:
    """항목 1개의 측정 결과.

    `unmeasurable_reason`이 있으면 이 항목은 분모에서 빠진다 — 그 사유가 곧 도구가
    무엇을 못 쟀는지에 대한 정직한 기록이다.
    """

    kebab_id: str
    unmeasurable_reason: str | None
    reaches_when_refuted: bool = False
    worst_phrase: str = ""

    @property
    def measurable(self) -> bool:
        return self.unmeasurable_reason is None


def _control_text(misconception: Misconception) -> str:
    """오개념을 *주장하는* 대조군 문장 — 신호를 공출현시킨다.

    `canonical_statement`를 붙이지 **않는다**: 그 문장이 항목 자신의 `refuting_regex`를
    밟을 수 있어(모듈 docstring의 `root-loss-by-dividing` 사례) 대조군이 스스로 죽는다.
    신호만 늘어놓는 것이 "이 항목이 발화하는 최소 텍스트"에 가장 가깝다.
    """
    return " ".join(misconception.signals)


def build_probes() -> tuple[CorrectionProbe, ...]:
    """카탈로그 전건에 대해 대조군·정정 변형을 결정론 생성한다(무작위 0·라이브 0)."""
    return tuple(
        CorrectionProbe(
            kebab_id=m.id,
            control=_control_text(m),
            refuted=tuple(_control_text(m) + phrase for phrase in CORRECTION_PHRASES),
        )
        for m in CATALOG
    )


def _reaches_student(kebab_id: str, text: str) -> bool:
    """이 텍스트에서 그 오개념이 **서빙 품질 게이트를 넘어** 학생에게 도달하는가."""
    gated = apply_match_quality_gate(diagnose(text, top_k=len(CATALOG_BY_ID)))
    return any(m.misconception.id == kebab_id for m in gated.matches)


def _evaluate_one(probe: CorrectionProbe) -> ProbeResult:
    misconception = CATALOG_BY_ID[probe.kebab_id]

    if not probe.control.strip():
        return ProbeResult(probe.kebab_id, "signals 없음 — 대조군을 만들 수 없다")
    if is_refuted(misconception, probe.control):
        # 신호 문자열 자체가 항목의 반박 조건을 밟은 경우. 도구의 한계이지 관측 결과가 아니다.
        return ProbeResult(probe.kebab_id, "대조군이 항목 자신의 refuting_regex를 밟음")
    if not _reaches_student(probe.kebab_id, probe.control):
        return ProbeResult(probe.kebab_id, "대조군이 서빙 게이트에 도달하지 못함")

    for text, phrase in zip(probe.refuted, CORRECTION_PHRASES, strict=True):
        if _reaches_student(probe.kebab_id, text):
            return ProbeResult(probe.kebab_id, None, reaches_when_refuted=True, worst_phrase=phrase)
    return ProbeResult(probe.kebab_id, None, reaches_when_refuted=False)


#: 앞절이 **이 오개념과 무관한 다른 것**을 정정하는 접두 — 오억제 측정용 (MISC-28).
#:
#: 세 연결어미(`-지만`·`-어서`·`-는데`)를 밟되 **정정 어휘는 `잘못` 하나로 고정**한다.
#: 어휘를 함께 바꾸면 연결어미의 효과와 어휘의 효과가 섞여 측정이 무의미해진다 — 1차
#: 측정에서 실제로 그랬다(`-는데` 접두만 정정 어휘가 없어 오억제 0%가 나왔고, 그것을
#: "연결어미 차이"로 읽을 뻔했다). 마지막 항목은 **대조군**이다: 정정 어휘가 없으면
#: 억제가 일어나지 않아야 한다. 없으면 "무엇이든 억제"라는 과잉 억제와 구별되지 않는다.
FOREIGN_CORRECTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("-지만", "부호를 잘못 옮겨 적었지만 "),
    ("-어서", "부호를 잘못 옮겨 적어서 "),
    ("-는데", "부호를 잘못 옮겨 적었는데 "),
    ("[대조군] 정정어휘 없음", "부호를 다시 확인했는데 "),
)

#: 대조군 접두의 라벨 — 이 항목만 "억제되지 않아야 정상"이다.
_CONTROL_PREFIX_LABEL = "[대조군] 정정어휘 없음"


@dataclass(frozen=True)
class OverSuppressionResult:
    """항목 1개 × 접두 1개의 오억제 측정 결과."""

    kebab_id: str
    prefix_label: str
    suppressed: bool


def measure_over_suppression() -> tuple[OverSuppressionResult, ...]:
    """**반대 방향**을 잰다 — 진단돼야 하는데 억제되는가 (MISC-28 acceptance ④).

    이 모듈의 원래 축(사각)은 "정정했는데 진단이 나가는가"만 본다. 그 축만 보면 **과잉
    억제가 개선으로 보인다** — 무엇이든 억제하면 사각은 0%가 되기 때문이다. 그래서
    반대 방향을 같은 화면에 낸다.

    형태: `<다른 것을 정정하는 앞절> <연결어미> <이 오개념 주장>`. 정정 대상이 *다른
    것*이므로 이 오개념은 **진단돼야 한다**. 억제되면 오억제다.

    대조군(`_control_text`만)이 서빙 게이트에 도달하지 못하는 항목은 애초에 억제를 잴 수
    없으므로 결과에서 빠진다 — 사각 축의 `unmeasurable`과 같은 이유다.
    """
    results: list[OverSuppressionResult] = []
    for misconception in CATALOG:
        base = _control_text(misconception)
        if not _reaches_student(misconception.id, base):
            continue  # 대조군 미발화 — 억제 여부를 물을 수 없다
        for label, prefix in FOREIGN_CORRECTION_PREFIXES:
            results.append(
                OverSuppressionResult(
                    kebab_id=misconception.id,
                    prefix_label=label,
                    suppressed=not _reaches_student(misconception.id, prefix + base),
                )
            )
    return tuple(results)


#: 정정 라벨을 **앞**에 붙이는 형태 — 정당한 반박인데 어순 규칙만으로는 억제되지 않는다.
#:
#: MISC-25가 막은 사각(`CORRECTION_PHRASES`)은 전부 *후치*다("…라는 풀이는 틀렸다"). 전치
#: 라벨은 그 창으로는 안 잡히고 lookbehind 창이 잡는데, MISC-28 ⓒ가 그 창의 판정을
#: 억제에서 **보류**로 바꿨다. 그래서 이 형태는 이제 학생에게 *도달한다* — 보류 플래그를
#: 달고. 그 사실이 화면에 없으면 ⓒ의 비용이 보이지 않는다.
#:
#: 마지막 항목은 **대조군**이다: 정정 어휘가 없는 접두이므로 도달하되 **보류되면 안 된다**.
#: 없으면 `held`가 `reaches`와 구별되지 않아 이 축 전체가 위장이 된다 — 실제로 뮤테이션
#: M13(`held=bool(hit)`, 즉 "도달하면 보류로 친다")이 대조군 없이는 **살아남았다**.
PREFIX_CORRECTION_LABELS: tuple[str, ...] = (
    "틀린 풀이: ",
    "오답 예시 — ",
    "잘못된 풀이는 ",
    "참고로 적어 보면 ",
)

#: 대조군 접두 — 이 항목만 "보류되지 않아야 정상"이다.
_CONTROL_PREFIX_LABEL_TEXT = "참고로 적어 보면 "


@dataclass(frozen=True)
class HeldVerdictResult:
    """항목 1개 × 전치 라벨 1개 — 도달했는가 / 보류 플래그가 붙었는가 (MISC-28 ⓒ).

    잡아야 하는 실패는 `reaches and not held` 하나다 — **확신 진단이 그대로 나가는** 상태.
    `not reaches`는 종전의 억제(ⓒ 이전 동작)이고, `reaches and held`가 ⓒ의 의도다.
    """

    kebab_id: str
    label: str
    reaches: bool
    held: bool

    @property
    def is_control(self) -> bool:
        """정정 어휘가 없는 대조군 행 — 보류되지 **않아야** 정상이라 누출 집계에서 뺀다."""
        return self.label == _CONTROL_PREFIX_LABEL_TEXT

    @property
    def confident_and_wrong(self) -> bool:
        return self.reaches and not self.held and not self.is_control


def measure_held_verdicts() -> tuple[HeldVerdictResult, ...]:
    """전치 정정 라벨에서 **확신 진단이 새는가**를 잰다 (MISC-28 ⓒ 집행 지점).

    ⓒ는 전치 정정을 억제하지 않으므로 사각 축(`gap`)이 이 형태를 더는 0%로 보증하지
    않는다. 대신 보증해야 하는 것이 바뀐다 — *도달하되 보류돼야 한다*. 이 함수가 그
    새 보증을 측정한다. 없으면 ⓒ 도입이 "오억제 100%→3%"라는 **좋은 숫자만** 남기고
    그 대가를 감춘다.
    """
    results: list[HeldVerdictResult] = []
    for misconception in CATALOG:
        base = _control_text(misconception)
        if not base.strip() or is_refuted(misconception, base):
            continue
        if not _reaches_student(misconception.id, base):
            continue  # 대조군 미발화 — 도달 여부를 물을 수 없다
        for label in PREFIX_CORRECTION_LABELS:
            text = label + base
            gated = apply_match_quality_gate(diagnose(text, top_k=len(CATALOG_BY_ID)))
            hit = [m for m in gated.matches if m.misconception.id == misconception.id]
            results.append(
                HeldVerdictResult(
                    kebab_id=misconception.id,
                    label=label,
                    reaches=bool(hit),
                    held=bool(hit) and hit[0].attribution_unclear,
                )
            )
    return tuple(results)


@dataclass(frozen=True)
class GapReport:
    """전수 측정 결과 — 분모를 항상 함께 낸다."""

    results: tuple[ProbeResult, ...]

    @property
    def measurable(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.measurable)

    @property
    def gap(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.measurable if r.reaches_when_refuted)

    @property
    def gap_ratio(self) -> float | None:
        """사각 비율. **측정 가능 항목이 0이면 0.0이 아니라 `None`**(분모 없는 0 금지)."""
        if not self.measurable:
            return None
        return len(self.gap) / len(self.measurable)

    def to_json(self) -> dict[str, object]:
        return {
            "catalog_total": len(self.results),
            "measurable": len(self.measurable),
            "gap": len(self.gap),
            "gap_ratio": self.gap_ratio,
            "gap_ids": [r.kebab_id for r in self.gap],
            "unmeasurable": [
                {"id": r.kebab_id, "reason": r.unmeasurable_reason}
                for r in self.results
                if not r.measurable
            ],
        }


def evaluate() -> GapReport:
    return GapReport(tuple(_evaluate_one(p) for p in build_probes()))


def format_report(report: GapReport) -> str:
    lines = [
        "=" * 70,
        "명시적 정정 언급 사각 — 학생이 부정했는데도 진단이 도달하는가 (MISC-25)",
        "=" * 70,
        f"  카탈로그 전체 : {len(report.results)}종",
        f"  측정 가능     : {len(report.measurable)}종 (대조군이 서빙 게이트에 도달한 항목)",
    ]
    ratio = report.gap_ratio
    if ratio is None:
        lines.append("  사각 비율     : 측정 불가 — 측정 가능 항목이 0종이다(통과 아님)")
    else:
        lines.append(f"  사각          : {len(report.gap)}/{len(report.measurable)} ({ratio:.1%})")
    if report.gap:
        lines.append("")
        lines.append("  [사각 항목] 정정 어구가 있는데도 학생에게 도달한다:")
        for r in report.gap:
            lines.append(f"    · {r.kebab_id:<44} ← {r.worst_phrase!r}")
    unmeasurable = [r for r in report.results if not r.measurable]
    if unmeasurable:
        lines.append("")
        lines.append("  [측정 불가] 분모에서 제외 — 사유별:")
        for r in unmeasurable:
            lines.append(f"    · {r.kebab_id:<44} {r.unmeasurable_reason}")

    # ── 반대 방향 (MISC-28) ───────────────────────────────────────────────
    # 사각만 보면 **과잉 억제가 개선으로 보인다**. 무엇이든 억제하면 사각은 0%가 되기
    # 때문이다. 그래서 같은 화면에 반대 방향을 낸다 — 한쪽만 보고 "해결됐다"고 적는 일이
    # 없게. 이 표가 없던 동안 "사각 0%"는 그 자체로는 참이었지만 오억제 100%를 가렸다.
    over = measure_over_suppression()
    if over:
        lines.append("")
        lines.append("  [반대 방향] 오억제 — 다른 것을 정정했는데 이 오개념까지 억제되는가:")
        for label, _prefix in FOREIGN_CORRECTION_PREFIXES:
            rows = [r for r in over if r.prefix_label == label]
            hit = sum(1 for r in rows if r.suppressed)
            note = " ← 억제되면 안 된다" if label == _CONTROL_PREFIX_LABEL else ""
            lines.append(
                f"    · {label:<22} {hit:>3}/{len(rows):<3} ({hit / len(rows):6.1%}){note}"
            )

    # ── 세 번째 축 (MISC-28 ⓒ) ────────────────────────────────────────────
    # ⓒ가 전치 정정을 억제에서 *보류*로 바꿨으므로 사각 축은 이 형태를 더는 0%로 보증하지
    # 않는다. 그래서 새 보증("도달하되 보류")을 같은 화면에 낸다 — 이 표가 없으면 위 두 표가
    # "오억제 100%→3%"라는 좋은 숫자만 남기고 그 대가를 감춘다.
    held = measure_held_verdicts()
    if held:
        lines.append("")
        lines.append("  [보류 축] 전치 정정 라벨 — 도달하되 **확신을 보류**하는가 (ⓒ):")
        for label in PREFIX_CORRECTION_LABELS:
            held_rows = [r for r in held if r.label == label]
            if label == _CONTROL_PREFIX_LABEL_TEXT:
                # 대조군은 "보류된 수"를 센다 — 0이어야 정상(정정 어휘가 없으니 보류할 게 없다).
                hit = sum(1 for r in held_rows if r.held)
                lines.append(
                    f"    · {label!r:<18} 보류    {hit:>3}/{len(held_rows):<3} "
                    f"({hit / len(held_rows):6.1%}) ← [대조군] 보류되면 안 된다"
                )
                continue
            leaked = sum(1 for r in held_rows if r.confident_and_wrong)
            lines.append(
                f"    · {label!r:<18} 확신 누출 {leaked:>3}/{len(held_rows):<3} "
                f"({leaked / len(held_rows):6.1%}) ← 0이어야 한다"
            )
        reaching = sum(1 for r in held if r.reaches)
        lines.append(
            f"    (참고) 도달 {reaching}/{len(held)} — ⓒ 이전에는 정정 라벨이 전부 억제됐다. "
            "억제가 아니라 보류가 된 것이 이 축의 변화다."
        )
    lines.append("=" * 70)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.explicit_correction_gap_eval",
        description=(
            "학생이 오개념을 명시적으로 부정한 텍스트에서 그 오개념 진단이 서빙 게이트를 "
            "넘어 도달하는 비율을 카탈로그 전수로 잰다(MISC-25 · hermetic·DB 0·LLM 0)."
        ),
    )
    parser.add_argument(
        "--max-gap-ratio",
        type=float,
        default=None,
        help="사각 비율 상한 — 초과하면 exit 1(기본 미지정=측정만).",
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

    ratio = report.gap_ratio
    if ratio is None:
        # 잰 것이 없다 — 기준 미달이 아니라 측정 실패다(스캔 0건은 실패).
        print(
            "[측정 불가] 대조군이 도달한 항목이 0종 — 카탈로그·게이트·생성기 중 하나가 깨졌다.",
            file=sys.stderr,
        )
        return _EXIT_UNMEASURABLE
    if args.max_gap_ratio is not None and ratio > args.max_gap_ratio:
        print(
            f"[게이트 미달] 사각 비율 {ratio:.1%} > 상한 {args.max_gap_ratio:.1%}",
            file=sys.stderr,
        )
        return _EXIT_FAIL
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
