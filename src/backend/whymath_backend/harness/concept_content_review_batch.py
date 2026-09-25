"""개념 콘텐츠 LLM 배치 검수 — Wilson min-n 샘플링 + rubric + JSONL 감사 리포트.

이 도구는 사람 검수 전 *기계 선별* 단계다. 전체 846건(K-12 437 + 대학 409)을 모두 검수하지
않고, 원하는 결함율 상한(기본 5%)을 보장할 수 있는 최소 표본(min-n)만 LLM rubric으로 평가한다.
표본은 결정론적 난수 시드로 추출하며, 결함 주입 표본을 몇 건 섞어 rubric이 실제로 결함을
잡는지 변별력을 확인한다. 최종 산출물은 JSONL 감사 리포트 + 사람이 승인할 후보 목록이다.

사용:
    python -m whymath_backend.harness.concept_content_review_batch
        [--threshold 0.05] [--confidence 0.95] [--seed 42]
        [--model local:quality|local:math:mid|local:general:mid]
        [--out out/review_batch.jsonl] [--dry-run | --fake-llm]

exit code:
    0 — LLM이 모든 주입 결함을 잡았고, 표본 결함율의 Wilson 95% 상한이 임계 이하.
    1 — rubric 변별력 실패(주입 결함 누락) 또는 결함율 상한 초과.
    2 — 입력 파일/모델 오류.

경계 메모:
  - LLM 응답은 검증 전 원시 출력이며, 이 도구는 *감사 신호*만 만든다. 학생 노출은 후속
    사람 승인(`concept_content_review_apply`) 후 `review_status='reviewed'`로 갱신해야 한다.
  - LLM 호출은 `l3/providers/ollama.OllamaProvider`를 경유한다(라우터 결정 bypass — 배치
    품질 검수는 동기 SLA가 없으므로 QUALITY 27b를 직접 지정). Ollama 미도달 시 2를 반환.
  - "값을 지어내지 않음" 원칙: LLM 응답 파싱 실패 시 해당 레코드는 defect로 기록하고 사유를
    남긴다. missing count를 0으로 조용히 대체하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l1.concept_content.projection import (
    ConceptContentRecord,
    load_concept_content_from_json,
)

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_INPUT_ERROR = 2

_DEFAULT_K12 = Path("data/corpus/concept_content_v1/content.json")
_DEFAULT_UNIV = Path("data/corpus/concept_content_university_v1/content.json")

# 로컬 루트 기준(레포 루트)에서 4단 상승: src/backend/whymath_backend/harness/ → 레포 루트.
_REPO_ROOT = Path(__file__).resolve().parents[4]

# rubric 기본 임계 — 95% 신뢰도 하 결함율 5% 상한. (상한 기준 값은 후속 사람 검수 용량과 맞춘다.)
_DEFAULT_THRESHOLD = 0.05
_DEFAULT_CONFIDENCE = 0.95

# LLM 품질 티어 → (패밀리, 크기) 매핑. QUALITY=27b, MID GENERAL=7b 일반·한국어, MID MATH=7b 수학.
_MODEL_TIER_MAP: dict[str, tuple[str | None, str]] = {
    "quality": (None, "quality"),  # qwen3.5:27b, 패밀리 무관
    "general:mid": ("general", "mid"),  # qwen2.5:7b
    "math:mid": ("math", "mid"),  # qwen2-math:7b
}


# ──────────────────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────────────────


def load_all_records(
    k12_path: Path | None = None,
    university_path: Path | None = None,
) -> list[ConceptContentRecord]:
    """K-12 + 대학 코퍼스를 모두 로드한다."""
    k12 = k12_path or _REPO_ROOT / _DEFAULT_K12
    univ = university_path or _REPO_ROOT / _DEFAULT_UNIV
    records: list[ConceptContentRecord] = []
    for path, scope in [(k12, CONTENT_SCOPE_K12), (univ, CONTENT_SCOPE_UNIVERSITY)]:
        if not path.exists():
            print(f"입력 오류: 코퍼스 없음 {path}", file=sys.stderr)
            raise FileNotFoundError(path)
        records.extend(load_concept_content_from_json(path, scope=scope))
    return records


# ──────────────────────────────────────────────────────────────────────────
# Wilson min-n 샘플링
# ──────────────────────────────────────────────────────────────────────────


def min_n_for_zero_defects(threshold: float, confidence: float = _DEFAULT_CONFIDENCE) -> int:
    """결함 0건 관측 시 threshold 이하의 Wilson 상한을 보장하는 최소 표본 수.

    n >= z^2 * (1 - threshold) / threshold  (x=0에서 Wilson 상한 정리식).
    """
    import statistics

    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold는 (0,1)이어야 합니다: {threshold}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence는 (0,1)이어야 합니다: {confidence}")
    z = statistics.NormalDist().inv_cdf(confidence)
    return max(1, math.ceil(z * z * (1.0 - threshold) / threshold))


def stratified_sample(
    records: list[ConceptContentRecord],
    n: int,
    *,
    seed: int,
) -> list[ConceptContentRecord]:
    """scope(K-12/대학) 비율에 맞게 결정론적 표본 추출."""
    rng = random.Random(seed)
    by_scope: dict[str, list[ConceptContentRecord]] = {}
    for r in records:
        by_scope.setdefault(r.scope, []).append(r)

    sampled: list[ConceptContentRecord] = []
    total = len(records)
    remaining = n
    scopes = sorted(by_scope)
    # 비율 할당; 마지막 scope은 남은 수를 모두 배정(반올림 누락 보정).
    for idx, scope in enumerate(scopes):
        pool = list(by_scope[scope])
        if idx == len(scopes) - 1:
            k = remaining
        else:
            k = max(1, min(remaining, math.floor(n * len(pool) / total))) if len(pool) > 0 else 0
            if remaining <= 0:
                k = 0
        k = min(k, len(pool))
        rng.shuffle(pool)
        sampled.extend(pool[:k])
        remaining -= k
    return sampled


# ──────────────────────────────────────────────────────────────────────────
# 결함 주입 표본
# ──────────────────────────────────────────────────────────────────────────


def _injected_defects() -> list[ConceptContentRecord]:
    """rubric 변별력 확인용 인공 결함 레코드."""
    return [
        ConceptContentRecord(
            code="__INJECT_BAD_METAPHOR__",
            scope=CONTENT_SCOPE_K12,
            name="주입: 부적절 은유",
            subject="초등수학",
            unit="수와 연산",
            metaphor="이 개념은 그냥 외우세요. 외우면 다 됩니다.",
            misconception="학생이 둔해서 못 알아듣는다.",
            formal_definition_internal="올바른 정의입니다.",
            accepted_expressions="정상 표현",
            explanation="2022 개정 내용을 중심으로 설명한다.",  # 기존 감사도 잡는 잔류
            standard_codes=(),
            flashcards=(),
            review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
        ),
        ConceptContentRecord(
            code="__INJECT_WRONG_MATH__",
            scope=CONTENT_SCOPE_UNIVERSITY,
            name="주입: 잘못된 정의",
            subject="미적분학",
            unit="극한",
            metaphor="극한은 마법의 벽이다.",
            misconception="극한은 그냥 대입하면 된다.",
            formal_definition_internal="lim_{x→a} f(x) = f(a)는 항상 성립한다.(틀림)",
            accepted_expressions="f(a)로 대입",
            explanation="극한을 계산할 때는 항상 함수값을 대입한다.",
            standard_codes=(),
            flashcards=(),
            review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
        ),
    ]


def _control_records() -> list[ConceptContentRecord]:
    """rubric 오검출(false positive) 확인용 **깨끗한** 대조 레코드.

    주입 결함과 1:1로 짝을 이룬다 — 같은 scope·같은 결함 축을 다루되 정답이 반대다.
    `_injected_defects()`만 있으면 "결함을 놓쳤는가"(false negative)만 측정되고
    "멀쩡한 것을 결함으로 찍었는가"(false positive)는 측정되지 않는다. 그러면 표본
    결함율이 콘텐츠 품질인지 rubric 과민인지 가릴 수 없다(2026-09-23 1회차 실측:
    표본 52건 중 33건 결함 판정이 어느 쪽인지 판정 불가였다).

    이 레코드들은 `_RUBRIC_SYSTEM`의 6기준을 전부 만족하도록 만들었다 — 정확한 정의,
    학년 적합 은유, 비난 없는 오개념, 크롤링 잔류 없음, 필수 필드 완비, 모순 없음.
    """
    return [
        ConceptContentRecord(
            code="__CONTROL_GOOD_METAPHOR__",
            scope=CONTENT_SCOPE_K12,
            name="대조: 적절 은유",
            subject="초등수학",
            unit="수와 연산",
            metaphor="나눗셈은 사탕을 친구들에게 똑같이 나누어 주는 일과 같다.",
            misconception="나머지가 있으면 나눗셈이 틀린 것이라고 생각하기 쉽다.",
            formal_definition_internal=(
                "자연수 a를 b로 나누면 a = b × q + r (0 ≤ r < b)를 만족하는 몫 q와 나머지 r이 "
                "유일하게 정해진다."
            ),
            accepted_expressions="a ÷ b = q … r",
            explanation=(
                "똑같이 나누어 주고 남는 것이 나머지다. 남는 양이 나누는 수보다 작아야 "
                "더 나누어 줄 수 없다는 뜻이므로, 나머지는 항상 나누는 수보다 작다."
            ),
            standard_codes=(),
            flashcards=(),
            review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
        ),
        ConceptContentRecord(
            code="__CONTROL_CORRECT_MATH__",
            scope=CONTENT_SCOPE_UNIVERSITY,
            name="대조: 올바른 정의",
            subject="미적분학",
            unit="극한",
            metaphor="극한은 목적지에 닿지 않고도 얼마든지 가까워질 수 있다는 약속이다.",
            misconception="극한값이 그 점의 함수값과 항상 같다고 생각하기 쉽다.",
            formal_definition_internal=(
                "임의의 ε > 0에 대해 δ > 0이 존재하여 0 < |x - a| < δ이면 |f(x) - L| < ε일 때, "
                "lim_{x→a} f(x) = L이라 한다."
            ),
            accepted_expressions="lim_{x→a} f(x) = L",
            explanation=(
                "극한은 x = a에서의 값이 아니라 a에 가까워질 때의 경향을 말한다. 따라서 "
                "f(a)가 정의되지 않아도 극한은 존재할 수 있고, 정의되더라도 극한값과 다를 수 있다."
            ),
            standard_codes=(),
            flashcards=(),
            review_status=CONTENT_REVIEW_STATUS_AI_ESTIMATED,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────
# LLM rubric
# ──────────────────────────────────────────────────────────────────────────
_RUBRIC_SYSTEM = """당신은 WhyMath(와이매스) 개념 콘텐츠 검수자입니다.
다음 JSON 형식으로만 응답하세요:

{"passed": true/false, "defects": ["결함1", "결함2", ...], "reason": "종합 평가 한 문장"}

아래 개념 콘텐츠를 검수 기준에 따라 평가하세요.
defect는 구체적이고 짧게 쓰세요.
passed는 true일 때 defects는 빈 배열 []이어야 합니다.

검수 기준(한 건이라도 위반이면 passed=false):
1. 수학적 정확성: formal_definition_internal이 틀리거나, 오개념/허용표현과 모순되면 안 된다.
2. 은유 적절성: metaphor가 대상 학년/수준에 맞고, 학습을 방해하지 않아야 한다.
3. 오개념 품질: misconception이 교육적으로 유용하고 비난/낙인이 아니어야 한다.
4. 잔류 표기: explanation에 '2022 개정', 페이지 번호, '(N) 절제목' 등 크롤링 잔류가 없어야 한다.
5. 필수 필드 결측: 은유·오개념·정식정의·허용표현·설명 중 하나라도 None/빈 값이면 결함이다.
6. 전후 일관성: flashcards(있을 경우)가 은유/오개념/정의와 모순되면 안 된다.
"""


def _build_prompt(record: ConceptContentRecord) -> str:
    """개념 레코드 → rubric 프롬프트."""
    return (
        f"code: {record.code}\n"
        f"scope: {record.scope}\n"
        f"과목: {record.subject}\n"
        f"단원: {record.unit or '(없음)'}\n"
        f"개념명: {record.name}\n"
        f"은유(metaphor): {record.metaphor or '(없음)'}\n"
        f"오개념(misconception): {record.misconception or '(없음)'}\n"
        f"정식정의(formal_definition_internal): {record.formal_definition_internal or '(없음)'}\n"
        f"허용표현(accepted_expressions): {record.accepted_expressions or '(없음)'}\n"
        f"설명(explanation): {record.explanation or '(없음)'}\n"
        f"암기카드 수: {len(record.flashcards)}\n"
    )


_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "defects": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["passed", "defects", "reason"],
}


@dataclass(frozen=True, slots=True)
class Assessment:
    """한 레코드에 대한 LLM 평가 결과."""

    code: str
    scope: str
    subject: str
    passed: bool
    defects: tuple[str, ...]
    reason: str
    sampled: bool
    injected: bool
    control: bool
    expected_pass: bool | None
    model: str
    latency_ms: float
    timestamp: str

    def to_jsonl(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "scope": self.scope,
            "subject": self.subject,
            "passed": self.passed,
            "defects": list(self.defects),
            "reason": self.reason,
            "sampled": self.sampled,
            "injected": self.injected,
            "control": self.control,
            "expected_pass": self.expected_pass,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


async def _assess_one(
    provider: Any,
    record: ConceptContentRecord,
    *,
    model_tier: str,
    injected: bool = False,
    control: bool = False,
    sampled: bool = True,
) -> Assessment:
    """단일 레코드에 대해 LLM rubric을 평가한다."""
    from whymath_backend.l3.models import CostTier, LocalModelTier, RoutingDecision

    decision = RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=None,
        local_model=LocalModelTier.QUALITY,
        mode="async",
        reason="concept_content_review_batch",
        est_latency_ms=0,
        est_cost_krw=0.0,
    )
    # 사용자가 지정한 티어로 재설정
    family, tier = _MODEL_TIER_MAP[model_tier]
    if tier == "quality":
        decision = decision.model_copy(
            update={
                "local_family": None,
                "local_model": LocalModelTier.QUALITY,
            }
        )
    else:
        from whymath_backend.l3.models import ModelFamily

        decision = decision.model_copy(
            update={
                "local_family": ModelFamily(family) if family else ModelFamily.MATH,
                "local_model": LocalModelTier(tier),
            }
        )

    start = datetime.now(timezone.utc)
    result = await provider.generate(
        prompt=_build_prompt(record),
        system=_RUBRIC_SYSTEM,
        decision=decision,
        json_schema=_JSON_SCHEMA,
    )
    latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000.0

    parsed = _parse_llm_response(result.text, record.code)
    # `passed`는 **LLM이 말한 그대로**다. 여기서 주입 결함을 False로 덮어쓰면
    # `missed_injected`(주입을 놓친 수)가 구조적으로 항상 0이 되어 변별력 검사가
    # 위장이 된다 — LLM이 주입 결함을 통째로 놓쳐도 같은 숫자가 나온다.
    # 참값은 `expected_pass`가 따로 들고, 판정은 둘을 비교해서 한다.
    return Assessment(
        code=record.code,
        scope=record.scope,
        subject=record.subject,
        passed=parsed["passed"],
        defects=tuple(parsed["defects"]) if not parsed["passed"] else (),
        reason=parsed["reason"],
        sampled=sampled,
        injected=injected,
        control=control,
        expected_pass=(False if injected else True if control else None),
        model=decision.local_model or "quality",
        latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _parse_llm_response(text: str, code: str) -> dict[str, Any]:
    """LLM 원시 텍스트에서 JSON을 추출·파싱. 실패 시 defect 기록."""
    clean = text.strip()
    # 코드펜스 제거
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines[0].startswith("```json"):
            clean = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])
        else:
            clean = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])
        clean = clean.strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        return {
            "passed": False,
            "defects": [f"llm_response_parse_error: {exc}"],
            "reason": "LLM 응답이 JSON이 아님",
        }
    if not isinstance(data, dict):
        return {
            "passed": False,
            "defects": ["llm_response_not_object"],
            "reason": "LLM 응답이 JSON object가 아님",
        }
    passed = bool(data.get("passed", False))
    defects = data.get("defects", [])
    reason = data.get("reason", "")
    if not isinstance(defects, list):
        defects = []
    if not isinstance(reason, str):
        reason = ""
    # passed=true인데 defects가 비어있지 않으면 불일치 — 보수적으로 실패 처리
    if passed and defects:
        passed = False
    return {"passed": passed, "defects": defects, "reason": reason}


# ──────────────────────────────────────────────────────────────────────────
# 감사 리포트
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class BatchReport:
    """배치 검수 최종 리포트."""

    total_records: int
    sample_size: int
    injected_count: int
    assessed: list[Assessment]
    threshold: float
    confidence: float
    control_count: int = 0
    discrimination_measured: bool = True
    """LLM이 실제로 돌았는가. dry-run은 False — 그때의 변별력 수치는 측정이 아니다."""

    def sampled_assessments(self) -> list[Assessment]:
        return [a for a in self.assessed if a.sampled and not a.injected and not a.control]

    def injected_assessments(self) -> list[Assessment]:
        return [a for a in self.assessed if a.injected]

    def control_assessments(self) -> list[Assessment]:
        return [a for a in self.assessed if a.control]

    @property
    def defective_sampled(self) -> int:
        return sum(1 for a in self.sampled_assessments() if not a.passed)

    @property
    def missed_injected(self) -> int:
        """주입 결함을 **놓친** 수 (false negative). 통과하면 안 되는데 통과시킨 것."""
        return sum(1 for a in self.injected_assessments() if a.passed)

    @property
    def false_positive_controls(self) -> int:
        """깨끗한 대조군을 **결함으로 찍은** 수 (false positive). rubric 과민의 직접 측정."""
        return sum(1 for a in self.control_assessments() if not a.passed)

    def defect_rate_upper(self) -> float | None:
        n = len(self.sampled_assessments())
        if n == 0:
            return None
        return wilson_upper_bound(self.defective_sampled, n, self.confidence)

    def to_json(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "sample_size": self.sample_size,
            "injected_count": self.injected_count,
            "threshold": self.threshold,
            "confidence": self.confidence,
            "control_count": self.control_count,
            "discrimination_measured": self.discrimination_measured,
            "defective_sampled": self.defective_sampled,
            "missed_injected": self.missed_injected,
            "false_positive_controls": self.false_positive_controls,
            "defect_rate_upper": self.defect_rate_upper(),
            "assessed_count": len(self.assessed),
        }

    def render(self) -> str:
        lines = [
            "=" * 72,
            "개념 콘텐츠 LLM 배치 검수 리포트",
            "=" * 72,
            f"전체 레코드: {self.total_records}건",
            f"표본: {self.sample_size}건 + 주입 결함: {self.injected_count}건"
            f" + 깨끗한 대조군: {self.control_count}건",
            f"임계: {self.threshold*100:.1f}% (confidence={self.confidence*100:.0f}%)",
            f"표본 결함 수: {self.defective_sampled}",
            f"표본 결함율 상한(Wilson): {self._fmt_upper()}",
            f"누락된 주입 결함(false negative): {self.missed_injected} / {self.injected_count}",
            f"오검출된 대조군(false positive): {self.false_positive_controls}"
            f" / {self.control_count}",
        ]
        if not self.discrimination_measured:
            lines.append("  → dry-run: LLM을 부르지 않았으므로 위 두 줄은 측정값이 아니다")
        if self.missed_injected > 0:
            lines.append("  → rubric 변별력 부족: 주입한 결함을 LLM이 모두 잡지 못함")
        if self.false_positive_controls > 0:
            lines.append(
                "  → rubric 과민: 깨끗한 대조군을 결함으로 찍었다."
                " 표본 결함율은 콘텐츠 품질이 아니라 rubric 판정을 재고 있을 수 있다"
            )
        if self.control_count == 0 and self.discrimination_measured:
            lines.append("  → 대조군 0건: 오검출을 측정하지 않았다(표본 결함율 해석 불가)")
        lines.append("=" * 72)
        return "\n".join(lines)

    def _fmt_upper(self) -> str:
        upper = self.defect_rate_upper()
        return "미상" if upper is None else f"{upper * 100:.1f}%"


# ──────────────────────────────────────────────────────────────────────────
# CLI 본체
# ──────────────────────────────────────────────────────────────────────────
def _build_provider(model_tier: str) -> Any:
    """CLI 지정 티어에 맞는 LLM provider를 만든다."""
    if model_tier not in _MODEL_TIER_MAP:
        raise ValueError(f"지원하지 않는 모델 티어: {model_tier}")
    from whymath_backend.l3.providers.ollama import OllamaProvider

    return OllamaProvider()


class _FakeProvider:
    """테스트용: 항상 passed=true, 단 주입 코드는 잡아낸다(변별력 확인)."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: Any,
        *,
        images: Any = None,
        temperature: float | None = None,
        json_schema: Any = None,
    ) -> Any:
        from whymath_backend.l3.models import GenerationResult, Usage

        code = ""
        for line in prompt.splitlines():
            if line.startswith("code:"):
                code = line.split(":", 1)[1].strip()
                break
        if "__INJECT" in code:
            passed = False
            defects = ["injected_defect_detected"]
            reason = "주입 결함이 감지됨"
        else:
            passed = True
            defects = []
            reason = "fake provider: 통과"
        payload = {"passed": passed, "defects": defects, "reason": reason}
        text = json.dumps(payload, ensure_ascii=False)
        return GenerationResult(
            text=text,
            usage=Usage(input_tokens=100, output_tokens=50, latency_ms=0.0),
        )


async def run_batch_review(
    *,
    k12_path: Path | None,
    university_path: Path | None,
    threshold: float,
    confidence: float,
    seed: int,
    model_tier: str,
    output_path: Path | None,
    dry_run: bool,
    fake_llm: bool,
) -> BatchReport:
    """배치 검수 실행(비동기)."""
    records = load_all_records(k12_path, university_path)
    total = len(records)
    sample_size = min(total, min_n_for_zero_defects(threshold, confidence))

    sampled = stratified_sample(records, sample_size, seed=seed)
    sampled_codes = {r.code for r in sampled}
    injected = _injected_defects()
    controls = _control_records()

    # 주입 결함(통과하면 안 됨)과 깨끗한 대조군(통과해야 함)은 표본 집합에 넣지 않고
    # 별도 평가한다 — 전자는 false negative를, 후자는 false positive를 측정한다.
    to_assess = list(sampled) + list(injected) + list(controls)

    provider: Any
    if dry_run:
        # dry-run: LLM 평가 없이 표본/주입 목록만 기록. 주입 결함은 '실패'로 표시해
        # gate가 의미없는 "누락"을 보고하지 않도록 한다.
        assessments = [
            Assessment(
                code=r.code,
                scope=r.scope,
                subject=r.subject,
                # dry-run은 LLM을 부르지 않으므로 참값을 그대로 채운다. 그 결과
                # 변별력 수치가 0/0으로 나오지만 그것은 "측정했더니 완벽"이 아니라
                # "측정하지 않았다"이며, `discrimination_measured=False`가 그것을 말한다.
                passed=not r.code.startswith("__INJECT"),
                defects=("dry-run: injected defect",) if r.code.startswith("__INJECT") else (),
                reason="dry-run: 평가 생략",
                sampled=r.code in sampled_codes,
                injected=r.code.startswith("__INJECT"),
                control=r.code.startswith("__CONTROL"),
                expected_pass=(
                    False
                    if r.code.startswith("__INJECT")
                    else True if r.code.startswith("__CONTROL") else None
                ),
                model="dry-run",
                latency_ms=0.0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            for r in to_assess
        ]
    else:
        if fake_llm:
            provider = _FakeProvider()
        else:
            provider = _build_provider(model_tier)

        assessments = []
        for r in to_assess:
            a = await _assess_one(
                provider,
                r,
                model_tier=model_tier,
                injected=r.code.startswith("__INJECT"),
                control=r.code.startswith("__CONTROL"),
                sampled=r.code in sampled_codes,
            )
            assessments.append(a)

    report = BatchReport(
        total_records=total,
        sample_size=sample_size,
        injected_count=len(injected),
        assessed=assessments,
        threshold=threshold,
        confidence=confidence,
        control_count=len(controls),
        discrimination_measured=not dry_run,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for a in report.assessed:
                f.write(json.dumps(a.to_jsonl(), ensure_ascii=False) + "\n")
        print(f"JSONL 감사 리포트: {output_path}")

    return report


def main(argv: list[str] | None = None) -> int:
    """배치 검수 CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.concept_content_review_batch",
        description="개념 콘텐츠 LLM 배치 검수 (Wilson min-n + rubric + JSONL).",
    )
    parser.add_argument("--k12", type=Path, default=None, help="K-12 content.json 경로.")
    parser.add_argument("--university", type=Path, default=None, help="대학 content.json 경로.")
    parser.add_argument(
        "--threshold", type=float, default=_DEFAULT_THRESHOLD, help="허용 결함율 상한(기본 0.05)."
    )
    parser.add_argument(
        "--confidence", type=float, default=_DEFAULT_CONFIDENCE, help="Wilson 신뢰도(기본 0.95)."
    )
    parser.add_argument("--seed", type=int, default=42, help="표본 추출 난수 시드.")
    parser.add_argument(
        "--model",
        type=str,
        default="quality",
        choices=list(_MODEL_TIER_MAP),
        help="LLM 티어(quality/general:mid/math:mid).",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSONL 감사 리포트 출력 경로.")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 표본만 계산·기록.")
    parser.add_argument("--fake-llm", action="store_true", help="테스트용 가짜 LLM provider 사용.")
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(
            run_batch_review(
                k12_path=args.k12,
                university_path=args.university,
                threshold=args.threshold,
                confidence=args.confidence,
                seed=args.seed,
                model_tier=args.model,
                output_path=args.out,
                dry_run=args.dry_run,
                fake_llm=args.fake_llm,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR
    except Exception as exc:  # noqa: BLE001 — Ollama 도달 불가 등 외부 실패
        print(f"실행 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    print(report.render())

    upper = report.defect_rate_upper()
    # 게이트는 **세 방향**으로 따로 판정한다. 셋을 한 숫자로 합치면 "rubric이 둔한 것"과
    # "rubric이 과민한 것"과 "콘텐츠가 나쁜 것"이 같은 실패로 보이고, 그러면 결과를 보고
    # 무엇을 고쳐야 할지 알 수 없다.
    if report.missed_injected > 0:
        print(
            f"게이트 실패: 주입 결함 {report.missed_injected}/{report.injected_count}건 누락"
            " — rubric 변별력 부족(false negative).",
            file=sys.stderr,
        )
        return _EXIT_GATE_FAIL
    if report.false_positive_controls > 0:
        print(
            f"게이트 실패: 깨끗한 대조군"
            f" {report.false_positive_controls}/{report.control_count}건을"
            " 결함으로 판정 — rubric 과민(false positive)."
            " 표본 결함율은 콘텐츠 품질이 아니라 rubric 판정을 재고 있을 수 있다.",
            file=sys.stderr,
        )
        return _EXIT_GATE_FAIL
    if upper is not None and upper > args.threshold:
        print(
            f"게이트 실패: 결함율 상한 {report._fmt_upper()} > 임계 {args.threshold*100:.1f}%.",
            file=sys.stderr,
        )
        return _EXIT_GATE_FAIL
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
