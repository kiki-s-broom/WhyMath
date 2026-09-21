"""앵커 커버 오개념의 *기계판정형* 탐지 채널 변별력 측정 (MISC-07).

이 모듈이 있는 이유
-------------------
G0 확정 앵커(A1~A6)에 귀속되는 오개념 중 L4 카탈로그에 좌석이 있는 것은 5종인데, 그 5종의
기계 채널(`regex_signals`·`canonical_wrong_form`) 커버가 **0**이었다(EOS-52 실측). 즉 앵커
구간의 오개념은 substring 공출현이라는 **단 하나의 표면 경로**로만 잡혔다. MISC-07이 그중
*기계로 판정 가능한* 흔적에 정규식 채널을 붙였고, 이 모듈은 그 채널이 **실제로 변별하는지**를
양성/음성 픽스처로 측정해 Wilson 경계로 exit 0/1을 낸다.

측정하는 것 — 채널당 3계급
--------------------------
  - `positive` — 오개념 흔적이 **확정적으로** 들어 있는 풀이. 검출돼야 한다(검출률 Wilson **하한**).
  - `negative` — 올바른 풀이·기호 일반형·인접 정답 형태. 검출되면 **안 된다**
    (오검출률 Wilson **상한**).
  - `ambiguous` — 원리상 구별 불가한 우연의 일치(예: f(x₀)=x₀). *정규식 발화 자체*(`ambiguous_
    fired`)는 게이트에 넣지 않고 보고만 한다 — 숨기면 오검출률이 실제보다 좋아 보이고, 음성에
    넣으면 원리상 통과 불가한 게이트가 된다. 다만 `ambiguous_serving_reach`(서빙 품질 게이트까지
    살아남은 수)는 **0으로 강제**한다(MISC-24) — 원리상 구별 불가한 텍스트가 학생에게 확신
    오진단으로 나가면 그 자체가 해악이므로, "발화했다"는 보고만 하되 "확신 진단으로 도달했다"는
    회귀를 잡는다.

픽스처는 템플릿 × 수치로 **결정론 생성**한다(난수 0·외부 I/O 0·LLM 0). 손으로 3건씩 적으면
표본이 작아 Wilson 하한이 구조적으로 게이트를 통과할 수 없다(3/3의 95% 하한은 0.44다).

정직 회계 — 채널을 못 붙인 것을 숨기지 않는다
---------------------------------------------
앵커 커버 5종 중 채널을 받은 것은 3종이고, 2종은 **표면 채널로 원리상 판정 불가**다:
  - `opposite-root-selected` — 어느 근이 "요구된" 근인지는 *발문*에 있다. 풀이 텍스트만 보는
    채널은 알 수 없다(doc #31이 같은 이유를 적는다).
  - `extremum-max-min-confused` — 극대·극소의 순서 판별은 함수의 계수 부호에서 나온다. 풀이
    표면에 그 판단이 문자열로 남지 않는다(doc #33이 "방향 판별은 임베딩/LLM-judged 후속").
이 2종은 리포트에 `unchannelable` 계급으로 사유와 함께 실린다 — "5종 중 3종"을 "커버 완료"로
읽지 못하게 한다.

사용:
    python -m whymath_backend.harness.anchor_detection_channel_eval
    python -m whymath_backend.harness.anchor_detection_channel_eval --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.match_gate import apply_match_quality_gate

_EXIT_OK = 0
_EXIT_FAIL = 1

#: 검출률 Wilson 하한 최소선. 채널이 오개념 흔적을 놓치면 앵커 구간이 다시 substring 단일
#: 경로로 돌아간다. 보수적으로 0.80(픽스처 전건 검출 시 n≈18에서 여유롭게 통과).
DETECTION_FLOOR = 0.80

#: 오검출률 Wilson 상한 최대선. 정답을 오개념으로 부르는 것이 놓치는 것보다 해롭다
#: (학생에게 틀렸다고 말하는 방향의 오류 — 결정 우선순위 #1 학생 정서).
FALSE_POSITIVE_CEILING = 0.10


@dataclass(frozen=True)
class ChannelFixtures:
    """채널 1개의 픽스처 3계급 — 전부 결정론 생성."""

    kebab_id: str
    anchor_id: str
    positives: tuple[str, ...]
    negatives: tuple[str, ...]
    ambiguous: tuple[str, ...] = ()


@dataclass(frozen=True)
class Unchannelable:
    """채널을 붙이지 **못한** 앵커 커버 오개념 — 사유를 데이터로 남긴다."""

    kebab_id: str
    anchor_id: str
    reason: str


#: 표면 채널로 원리상 판정 불가한 앵커 커버 오개념 (doc #31·#33이 같은 사유를 적는다).
UNCHANNELABLE: tuple[Unchannelable, ...] = (
    Unchannelable(
        kebab_id="opposite-root-selected",
        anchor_id="A4",
        reason=(
            "어느 근이 요구된 근인지는 발문에 있고 풀이 텍스트에 없다 — 풀이만 보는 표면 "
            "채널은 '3 대신 2를 답했다'의 정오를 판정할 수 없다(doc #31 동일 사유)."
        ),
    ),
    Unchannelable(
        kebab_id="extremum-max-min-confused",
        anchor_id="A6",
        reason=(
            "극대·극소의 순서는 삼차항 계수 부호에서 나오는 판단이라 풀이 표면에 문자열로 "
            "남지 않는다 — 방향 판별은 임베딩/LLM-judged 경로 소관(doc #33 명시)."
        ),
    ),
)

# ── 픽스처 생성 (결정론) ────────────────────────────────────────────────────
# 수치는 한·두·세 자리를 섞어 `(?!\d)` 경계(예: x=20이 a=2로 오검출)를 실제로 밟는다.
#
# **개수가 곧 게이트의 통과 가능성이다.** 오검출 상한 0.10은 음성 표본이 적으면 *오검출 0건
# 에서도* 통과 불가다 — 실측: Wilson 상한(0/20)=0.1192 · (0/24)=0.1013 · (0/28)=0.0881.
# 즉 n<=24에서는 완벽한 채널도 FAIL이라 게이트가 변별이 아니라 위장이 된다(batch_safety
# docstring의 "n=30에서 0.95는 만점에도 통과 불가" 선례와 같은 함정). 그래서 수치를 9종으로
# 늘려 채널당 음성 >=28을 확보한다. 이 관계는 `_gate_is_reachable`이 매 실행마다 재검사한다.
_ROOTS: tuple[int, ...] = (2, 3, 5, 7, 10, 12, 15, 21, 100)


def _factor_sign_flip() -> ChannelFixtures:
    pos = tuple(
        tpl.format(a=a)
        for a in _ROOTS
        for tpl in (
            "(x-{a})=0 이므로 x=-{a}",
            "인수분해하면 (x-{a})(x+1)=0, (x-{a})=0에서 x=-{a}",
            "(x-{a})=0 이니까 답은 x=-{a} 이다",
        )
    )
    neg = tuple(
        tpl.format(a=a)
        for a in _ROOTS
        for tpl in (
            "(x-{a})=0 이므로 x={a}",  # 올바른 풀이
            "(x+{a})=0 이므로 x=-{a}",  # 부호가 원래 +인 정답
            "(x-{a})=0 에서 x={a}, 검산하면 {a}-{a}=0",  # 검산까지 붙은 정답
        )
    ) + (
        "(x-a)=0이면 x=-a 라는 일반형 서술",  # 기호형 — substring 경로 소관(disjoint)
        # 경계: `(?!\d)`가 없으면 a=2가 `x=-20`의 앞부분에 붙어 오검출된다. 뮤테이션 M1이
        # 살아남아 드러난 공백 — 처음 적었던 `x=20`은 부호가 없어 애초에 매치되지 않으므로
        # 그 가드를 **한 번도 밟지 않는 위장 픽스처**였다.
        "(x-2)=0 이므로 x=-20 이라고 잘못 적었다",
        "(x-1)=0 이므로 x=-12 라고 적었다",
    )
    return ChannelFixtures("factor-sign-flip", "A4", pos, neg)


def _root_loss_by_dividing() -> ChannelFixtures:
    pos = tuple(
        tpl.format(b=b)
        for b in _ROOTS
        for tpl in (
            "x²={b}x 양변을 x로 나누면 x={b}",
            "x² = {b}x 이므로 양변을 x로 나눠 x={b} 이다",
            "x²={b}x 에서 x로 나누면 답은 x={b}",
        )
    )
    neg = tuple(
        tpl.format(b=b)
        for b in _ROOTS
        for tpl in (
            "x²={b}x → x(x-{b})=0 → x=0 또는 x={b}",  # 근 손실 없는 정답
            "x²={b}x 이므로 x=0, x={b} 두 근을 얻는다",
            "x²={b}x 에서 x(x-{b})=0, 따라서 x=0 과 x={b}",
        )
    ) + (
        "ax²=bx 의 양변을 x로 나누면 x=b/a",  # 기호형 — substring 경로 소관
        "x²=2x 양변을 x로 나누면 x=20 이라고 적었다",  # 경계
        # PR #1032 Codex P1 회귀 동결 — 0을 근으로 적는 방법은 `x=0` 하나가 아니다.
        # 아래 문장들은 전부 **올바른 설명**이고 리터럴 `x=0`을 포함하지 않는다. 최초 판의
        # 배제 조건(`x=0` 리터럴)은 이들을 통째로 놓쳐 정답을 오개념으로 불렀다.
        "x²=2x에서 양변을 x로 나누면 x=2만 나와서 안 되고 해는 0과 2다",
        "x²=3x 의 해는 0과 3이다",
        "x²=7x, 양변을 x로 나누면 x=7 만 남아 x=0 을 잃는다",
        "x²=10x 의 두 근은 0이나 10 이다",
        "x²=5x 양변을 x로 나누면 x=5 이지만 근이 0인 경우를 빠뜨리면 안 된다",
    )
    return ChannelFixtures("root-loss-by-dividing", "A4", pos, neg)


_EXTREMUM_X: tuple[int, ...] = (-1, -3, 1, 4, -12, 10, 6, -21, 15)


def _extremum_value_vs_point() -> ChannelFixtures:
    pos = tuple(
        tpl.format(x=x)
        for x in _EXTREMUM_X
        for tpl in (
            "극대는 x={x} 에서 나오므로 극댓값은 {x}",
            "극대가 되는 점은 x={x} 이고 따라서 극댓값은 {x} 이다",
            "f'=0의 해 중 극대는 x={x}, 그러므로 극댓값은 {x}",
        )
    )
    neg = tuple(
        tpl.format(x=x, v=abs(x) + 100)
        for x in _EXTREMUM_X
        for tpl in (
            "극대는 x={x} 에서 나오고 극댓값은 {v}",  # 값과 좌표를 구별한 정답
            "극대가 되는 점은 x={x}, 극댓값은 f({x})={v}",
            "극대는 x={x} 이고 극솟값은 {v}",  # 극솟값만 언급 — 이 채널 소관 아님
        )
    ) + ("극댓값은 함숫값이고 x좌표가 아니다 라는 서술",)
    # 우연의 일치 — f(x₀)=x₀. 정답도 같은 문자열이 되므로 원리상 구별 불가(게이트 제외·보고만).
    amb = tuple(f"극대는 x={x} 에서 나오고 극댓값은 {x} 이다 (f({x})={x} 인 함수)" for x in (2, 5))
    return ChannelFixtures("extremum-value-vs-point-confused", "A6", pos, neg, amb)


def build_fixtures() -> tuple[ChannelFixtures, ...]:
    """채널 픽스처 전건 — 결정론(같은 입력에 같은 출력)."""
    return (_factor_sign_flip(), _root_loss_by_dividing(), _extremum_value_vs_point())


# ── 측정 ────────────────────────────────────────────────────────────────────


def _channel_fired(kebab_id: str, text: str) -> bool:
    """이 텍스트에서 *그 오개념의 정규식 채널*이 실제로 발화했는가.

    `diagnose()`(생산 경로)를 그대로 쓴다 — 정규식을 직접 돌려 재면 "모듈이 잡는다"가 아니라
    "내 정규식이 잡는다"를 재게 되고, 매칭 파이프라인이 바뀌어도 이 측정은 초록으로 남는다.
    """
    for match in diagnose(text, top_k=len(CATALOG_BY_ID)):
        if match.misconception.id == kebab_id and match.matched_regex_signals:
            return True
    return False


def _survives_serving_gate(kebab_id: str, text: str) -> bool:
    """이 텍스트의 그 오개념이 **서빙 품질 게이트(top-1 floor 0.65)를 넘어** 살아남는가.

    정규식이 *발화했다*와 학생 경로에 *도달했다*는 다른 사실이다(PR #1032 Codex P2). 이 채널들의
    의도된 수치 입력에서는 기호 substring 신호가 0이라 정규식 단독 매치만 남는다. MISC-22(v1.5)
    이전에는 그 가산분이 substring 신호 1개와만 동등해 confidence=1/2=0.5 → floor 0.65 미만으로
    `apply_match_quality_gate`가 **후보 전체를 비웠다**(factor-sign-flip이 이렇게 한 번도 학생에게
    도달하지 못했다). MISC-22가 정규식 매치 1건을 신호 전체와 동등하게 가산하도록 confidence
    공식을 정정해 이 함수는 그 사실(도달 여부)을 계속 잰다 — "검출률 100%"가 곧 "쓰인다"로
    오독되지 않도록(작동 신호 없는 알고리즘 부착 금지) 채널 추가·정정 때마다 재측정한다.
    """
    gated = apply_match_quality_gate(diagnose(text, top_k=len(CATALOG_BY_ID)))
    return any(m.misconception.id == kebab_id for m in gated.matches)


@dataclass
class ChannelResult:
    """채널 1개의 측정 결과."""

    kebab_id: str
    anchor_id: str
    detected: int = 0
    positives: int = 0
    false_positives: int = 0
    negatives: int = 0
    ambiguous_fired: int = 0
    ambiguous_total: int = 0
    #: MISC-24 — 모호 픽스처 중 **서빙 품질 게이트(top-1 floor 0.65)까지 살아남은** 수. 위
    #: `ambiguous_fired`(정규식 발화 여부)와는 다른 축이다: "정규식이 매치했다"와 "학생에게 확신
    #: 오진단으로 나갔다"는 다른 사실이라(PR #1032 Codex P2가 `positive` 계급에 세운 것과 같은
    #: 구별). `passed`가 이 값을 **0으로 강제**한다 — 원리상 구별 불가한 우연의 일치가 서빙까지
    #: 도달하면 그 자체로 확신 오진단이므로, `positives`의 serving_reach(보고만)와 달리 여기는
    #: 보고에 그치지 않고 게이트로 쓴다.
    ambiguous_serving_reach: int = 0
    #: 양성 중 **서빙 게이트까지 살아남은** 수. 검출 수와 다를 수 있고, 0이어도 게이트는 통과한다
    #: — 서빙 결선은 acceptance ③이 D2 후속으로 명시 이관한 범위이기 때문이다. 다만 **보고한다**.
    serving_reach: int = 0
    misses: list[str] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)

    @property
    def detection_lower(self) -> float:
        return wilson_lower_bound(self.detected, self.positives)

    @property
    def false_positive_upper(self) -> float:
        return wilson_upper_bound(self.false_positives, self.negatives)

    @property
    def passed(self) -> bool:
        return (
            self.detection_lower >= DETECTION_FLOOR
            and self.false_positive_upper <= FALSE_POSITIVE_CEILING
            # MISC-24: 원리상 구별 불가한 우연의 일치가 서빙 게이트까지 살아남으면 그 자체로
            # 확신 오진단(학생 정서 최우선 위반)이므로, ambiguous_total이 0(픽스처 없는 채널)이든
            # 아니든 항상 강제한다 — ambiguous_total=0인 채널은 이 항이 트리비얼하게 참이다.
            and self.ambiguous_serving_reach == 0
        )

    def to_json(self) -> dict[str, object]:
        return {
            "kebab_id": self.kebab_id,
            "anchor_id": self.anchor_id,
            "detected": self.detected,
            "positives": self.positives,
            "detection_lower_bound": round(self.detection_lower, 4),
            "false_positives": self.false_positives,
            "negatives": self.negatives,
            "false_positive_upper_bound": round(self.false_positive_upper, 4),
            "ambiguous_fired": self.ambiguous_fired,
            "ambiguous_total": self.ambiguous_total,
            "ambiguous_serving_reach": self.ambiguous_serving_reach,
            "serving_reach": self.serving_reach,
            "passed": self.passed,
            "misses": self.misses[:5],
            "leaks": self.leaks[:5],
        }


def evaluate() -> list[ChannelResult]:
    """전 채널 측정 — 순수(파일 I/O 0·난수 0)."""
    results: list[ChannelResult] = []
    for fx in build_fixtures():
        r = ChannelResult(kebab_id=fx.kebab_id, anchor_id=fx.anchor_id)
        r.positives = len(fx.positives)
        r.negatives = len(fx.negatives)
        r.ambiguous_total = len(fx.ambiguous)
        for text in fx.positives:
            if _channel_fired(fx.kebab_id, text):
                r.detected += 1
            else:
                r.misses.append(text)
            if _survives_serving_gate(fx.kebab_id, text):
                r.serving_reach += 1
        for text in fx.negatives:
            if _channel_fired(fx.kebab_id, text):
                r.false_positives += 1
                r.leaks.append(text)
        for text in fx.ambiguous:
            if _channel_fired(fx.kebab_id, text):
                r.ambiguous_fired += 1
            if _survives_serving_gate(fx.kebab_id, text):
                r.ambiguous_serving_reach += 1
        results.append(r)
    return results


def _gate_is_reachable(positives: int, negatives: int) -> bool:
    """이 표본 수에서 *완벽한 채널*(전건 검출·오검출 0)이 **양쪽 경계를 다** 통과할 수 있는가.

    통과 불가면 그 게이트는 채널의 품질과 **무관하게** 항상 FAIL이다 — 완벽한 채널도 떨어뜨리는
    게이트는 변별이 아니라 위장이고, 사람이 결국 게이트를 끄게 만든다. 그래서 실패를 채널의
    탓으로 돌리지 않고 **게이트 자신의 결함**으로 따로 보고한다.

    두 축을 다 본다(PR #1032 Codex P2) — 최초 판은 음성 축만 봐서, 양성이 11건 미만으로 줄면
    전건 검출로도 하한 0.80에 못 닿는데 `unreachable`이 비어 있어 그 필연적 실패가 **채널 탓으로**
    보고됐다. 한쪽만 검사하는 도달 가능성 검사는 그 자체가 위장이다.
    """
    detection_ok = wilson_lower_bound(positives, positives) >= DETECTION_FLOOR
    false_positive_ok = wilson_upper_bound(0, negatives) <= FALSE_POSITIVE_CEILING
    return detection_ok and false_positive_ok


@dataclass(frozen=True)
class Report:
    """회차 리포트 — 텍스트 출력과 JSON이 **같은 객체**에서 나오게 하는 단일 원천.

    dict로 조립해 두 경로가 각자 키를 읽으면, 한쪽만 고쳐도 아무도 소리내지 않는다(그리고
    타입 검사가 `object`로 뭉개져 오타를 못 잡는다).
    """

    channels: tuple[ChannelResult, ...]
    empty_fixture_channels: tuple[str, ...]
    unreachable_gate_channels: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            bool(self.channels)
            and not self.empty_fixture_channels
            and not self.unreachable_gate_channels
            and all(c.passed for c in self.channels)
        )

    @property
    def anchor_covered_total(self) -> int:
        return len({c.kebab_id for c in self.channels} | {u.kebab_id for u in UNCHANNELABLE})

    def to_json(self) -> dict[str, object]:
        return {
            "channels": [c.to_json() for c in self.channels],
            "coverage": {
                "anchor_covered_total": self.anchor_covered_total,
                "channelled": sorted(c.kebab_id for c in self.channels),
                "unchannelable": [
                    {"kebab_id": u.kebab_id, "anchor_id": u.anchor_id, "reason": u.reason}
                    for u in UNCHANNELABLE
                ],
            },
            "thresholds": {
                "detection_floor": DETECTION_FLOOR,
                "false_positive_ceiling": FALSE_POSITIVE_CEILING,
            },
            "empty_fixture_channels": list(self.empty_fixture_channels),
            "unreachable_gate_channels": list(self.unreachable_gate_channels),
            "passed": self.passed,
        }


def build_report() -> Report:
    """리포트 조립 — 커버 회계(채널 있음/불가)를 항상 함께 낸다."""
    results = evaluate()
    return Report(
        channels=tuple(results),
        # 픽스처가 0건이면 게이트가 공허하게 통과한다(스캔 0건은 실패).
        empty_fixture_channels=tuple(
            r.kebab_id for r in results if r.positives == 0 or r.negatives == 0
        ),
        # 표본이 작아 *구조적으로* 통과 불가한 게이트를 채널 실패로 오독하지 않게 분리 보고한다.
        unreachable_gate_channels=tuple(
            r.kebab_id for r in results if not _gate_is_reachable(r.positives, r.negatives)
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.anchor_detection_channel_eval",
        description="앵커 커버 오개념의 정규식 탐지 채널 변별력 측정(Wilson 경계·exit 0/1).",
    )
    parser.add_argument("--json", action="store_true", help="리포트 JSON만 출력.")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        for ch in report.channels:
            mark = "PASS" if ch.passed else "FAIL"
            print(
                f"[{mark}] {ch.anchor_id} {ch.kebab_id}: "
                f"검출 {ch.detected}/{ch.positives}(하한 {ch.detection_lower:.4f}) · "
                f"오검출 {ch.false_positives}/{ch.negatives}"
                f"(상한 {ch.false_positive_upper:.4f}) · "
                f"모호 {ch.ambiguous_fired}/{ch.ambiguous_total}"
                f"(서빙도달 {ch.ambiguous_serving_reach} — 게이트 강제 0) · "
                f"서빙도달 {ch.serving_reach}/{ch.positives}"
            )
        print(
            f"\n앵커 커버 {report.anchor_covered_total}종 = "
            f"채널 {len(report.channels)}종 + 판정불가 {len(UNCHANNELABLE)}종"
        )
        for u in UNCHANNELABLE:
            print(f"  · [{u.anchor_id}] {u.kebab_id} — {u.reason}")
    if report.unreachable_gate_channels:
        sys.stderr.write(
            f"[게이트 도달 불가] {list(report.unreachable_gate_channels)} — 음성 표본이 적어 "
            f"오검출 0건에서도 상한 {FALSE_POSITIVE_CEILING}을 통과할 수 없다. 채널이 아니라 "
            "게이트의 결함이다(픽스처를 늘려라)\n"
        )
    if report.empty_fixture_channels:
        sys.stderr.write(
            f"[픽스처 공백] {list(report.empty_fixture_channels)} — 양성·음성이 0건인 채널은 "
            "게이트를 공허하게 통과시킨다\n"
        )
    return _EXIT_OK if report.passed else _EXIT_FAIL


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
