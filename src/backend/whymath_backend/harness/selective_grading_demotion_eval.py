"""선택형·수치 단답 서버 채점 결함 주입 강등전 — REC-08(관측·게이트 전용·권위 이관 0).

설계 정본: `docs/architecture/ai_recommendation_module_gap_review_2.md` §2 G1 후속.
Kiki 결정 2026-08-09 — 채점 권위 이관 여부(`REC-07`)를 REC-05의 *정적 커버리지 수치*만으로
즉결하지 않고, **결함 주입 강등전으로 채점 정확성을 먼저 측정한 뒤** 그 결과를 근거로
판단한다(옵션 C). 이 모듈이 그 측정을 낸다.

REC-05(`attempt_grading_shadow_report.classify_gradability`)가 "코퍼스에 채점할 **재료**가
있는가"(NLP-09 이후 실측 — A 선택형 1,612 · B 수치 단답 154 · C 조건 파생 12,268)를 쟀다면,
이 모듈은 "그 재료로 채점하면 **실제로 맞히는가**"를 잰다. 둘은 분리된 질문이고 REC-05는
폐기되지 않는다 —
이 강등전의 모집단 정의(A/B 버킷)를 `classify_gradability`가 그대로 공급한다(재정의 0).

  *수치 현행화(REC-09 회수 시점 2026-08-11)*: 원 구현(2026-08-10)은 A 1,616 · B 1,031로
  적었다. `QUAL-02`(PR #777)의 실중복 9레코드 은퇴로 코퍼스가 2,647→2,638이 되면서 두
  모집단도 A −4 · B −5 만큼 줄었다(회수 세션 실측).

  *수치 재현행화 및 전제 정정(NLP-10 · 2026-09-10)*: 위 문단은 이어서 "모집단 크기는 게이트
  표본 산정에 영향을 주지 않는다 — 두 버킷 모두 n=75를 압도적으로 넘는 풀이다"라고 적었다.
  **두 군데가 틀렸다.**
    ① 버킷당 소비는 n=75가 아니라 **150**이다. 결함 단계와 무결함 단계가 커서를 공유하므로
       각 단계가 75건씩 따로 먹는다(`_bucket_demand` 참조).
    ② "압도적"이 더 이상 성립하지 않는다. `NLP-09`가 파생 게이트를 미지수 이름에서 개수로
       옮기면서 분류 우선순위 A→C→B에 따라 6,976문항이 B에서 C로 승격됐다 —
       **B 7,130 → 154**(실측 2026-09-10). 요구 150에 대해 여유는 **4건**이다.
  즉 모집단 크기는 게이트의 *통과 여부*가 아니라 **실행 가능 여부**를 좌우한다. 표본 n=150은
  여전히 코퍼스가 아니라 규약(오검출 상한 2%)에서 역산된 값이므로 줄일 수 없다 — 줄이면
  Wilson 상한이 규약을 증명하지 못해 게이트가 공허해진다. 그러므로 부족은 "요청을 줄여" 해소할
  것이 아니라 **판정 불가(exit 2)로 표면화**하고 모집단 쪽에서 푼다. 후속 설계는 `NLP-10`.
  검출 성능 자체는 무변화다(NLP-09 이후 재실측: 150/150 · 하한 0.982 · 오검출 0/150 ·
  상한 0.018 · undecidable 0).

────────────────────────────────────────────────────────────────────────────
왜 결함 주입인가 — 인간 라벨 0건으로 정답지가 성립한다
────────────────────────────────────────────────────────────────────────────
`docs/standards/superhuman_verification_standard.md` §3: 기계를 채점할 정답지(GT)를 인간
라벨에 의존하면 순환이다. 결함을 **우리가 의도적으로 주입**하므로 정답을 이미 안다 —
"이 학생 제출은 오답이어야 한다"가 주입 사실 자체로 확정된다. `l3/equivalent/defect_seeder.py`
가 세운 패턴(결정론 seed·런타임 산출·커밋 0·풀 소진 시 예외)을 승계하되, 그 함수 자체는
`CandidateProblem`(생성 파이프라인 번들) 전용이라 `Problem`(코퍼스) 기반인 여기서는 쓸 수
없다 — 패턴만 차용한다.

────────────────────────────────────────────────────────────────────────────
비교기 — 왜 `identity_status`인가 (acceptance② 정정 근거)
────────────────────────────────────────────────────────────────────────────
태스크 초안은 B버킷 비교기로 `l3/verify_answer`를 지목했으나 **정정했다**(2026-08-10):
`verify_answer(conditions, answer_map)`의 첫 인자는 *원 조건 수식*이 필수이고, 그 함수가
답하는 질문은 "답이 원 조건을 만족하는가"다. 그런데 B버킷은 **정의상 `conditions_parsed
[*].formal`이 없는 문항군**이라(그게 C버킷이 0건인 이유다) 조건을 합성해 넣어야 한다.
`l3/symbolic_equivalence.py:3-8`이 "동치 권위는 SymPy 단일 … 과거 `verify_step`에 인라인돼
'동치 권위가 둘'이 되는 부채였다"고 경고한 바로 그 우회로다.

`identity_status(lhs, rhs)`는 질문이 정확히 일치하고("두 값이 같은가") **4상태**라 판정
불가를 정직하게 분리할 수 있다(실측: `0.5`↔`1/2` identity · `1/3` vs `0.333` not_identity ·
`½` undecidable · `03` parse_error). acceptance②의 의도("SymPy 동치 권위 재사용·새 확률모델
0")는 그대로 보존된다 — 오히려 동치 판정의 *단일 권위* 정본을 직접 쓴다.

**A버킷 정규화에 NFKC를 쓰지 않는다**: NFKC는 `③`→`3`(선지 라벨이 선지 값으로 붕괴)·
`x²`→`x2`(지수 파괴)로 **의미를 변형**해 acceptance②의 "의미 변형 정규화 0"을 위반한다.
공백 + 전각 영숫자만 접는 화이트리스트 정규화(`normalize_choice_answer`)를 쓴다. 코퍼스
실측상 A버킷 1,612건 전건이 정규화 없이 정확일치라 실질 no-op이지만 계약을 문자로 지킨다
(회수 세션 2026-08-11 재실측 — 원 구현 시점 1,616건에서도 전건 no-op이었고, `QUAL-02`
중복 은퇴 후 1,612건에서도 전건 no-op이다. 계약을 지키는 이유는 실측이 아니라 *미래 코퍼스*
에 전각 표기가 유입될 때 조용히 오답 처리되는 것을 막기 위해서다).

────────────────────────────────────────────────────────────────────────────
정직 회계 — 판정 불가는 오답이 아니다 (교수학 금기 승계)
────────────────────────────────────────────────────────────────────────────
`attempt_grading_shadow_report.py`가 세운 두 계약을 그대로 승계한다:
  - **`undecidable`을 오답으로 강등하지 않는다** — 결함 trial에서 undecidable은 "검출"이
    아니고(보수적), 무결함 trial에서 undecidable은 "오검출"이 아니다(학생 무해).
  - **분모 없는 0 금지** — 표본 0이면 Wilson 경계는 `None`이고, `None`은 게이트 **실패**로
    처리한다(무측정을 통과로 위장하지 않는다).
`undecidable_*_count`를 별도 노출하는 이유: 대부분을 undecidable로 흘리는 채점기는 오검출률이
낮게 나와도 **실효 커버리지가 낮다**. 그 사실이 리포트에서 보여야 한다(NLP-02의
`unverifiable_rate`와 같은 역할).

────────────────────────────────────────────────────────────────────────────
범위 밖 동결 (acceptance⑤)
────────────────────────────────────────────────────────────────────────────
이 게이트가 PASS해도 **채점 권위는 이관되지 않는다** — 클라 배선·attempt 입력 소비·
`is_correct` 대체 전부 0이다. PASS/FAIL과 두 Wilson 값은 `REC-07`(owner=kiki)의 *입력*일 뿐
실행이 아니다. 이 모듈은 코퍼스 JSONL만 읽고(DB 0·LLM 0·네트워크 0) 라이브 요청 경로를
일절 건드리지 않는다.

사용:
    python -m whymath_backend.harness.selective_grading_demotion_eval
    python -m whymath_backend.harness.selective_grading_demotion_eval \
        --min-detection-lower 0.95 --max-false-alarm-upper 0.02
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, get_args

import sympy

from whymath_backend.harness.attempt_grading_shadow_report import (
    GradabilityBucket,
    classify_gradability,
)
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l1.problem_bank.populate import _AUTHORING_KEYS
from whymath_backend.l3.symbolic_equivalence import IdentityVerdict, identity_status
from whymath_backend.schema.problem import Problem

__all__ = [
    "SELECTIVE_DEFECT_CLASSES",
    "BucketHeadroom",
    "InsufficientPoolError",
    "SelectiveDefectClass",
    "SelectiveDemotionReport",
    "SelectiveGrade",
    "SelectiveTrial",
    "build_selective_demotion_set",
    "bucket_headroom",
    "format_headroom",
    "format_report",
    "grade_selective",
    "load_corpus_problems",
    "main",
    "normalize_choice_answer",
    "summarize",
]

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 측정 실패는 기준 미달과 **다른 종료 코드**다(NLP-10).
#
# 왜 나누는가: 이 둘은 CI에서 똑같이 red지만 요구하는 대응이 정반대다.
#   · exit 1(기준 미달) = 채점기가 결함을 놓쳤거나 맞은 답을 틀렸다고 했다 → 채점기를 고친다.
#   · exit 2(측정 실패) = 표본을 못 모아 **판정 자체를 못 했다** → 통과도 실패도 아니다.
# 같은 코드로 뭉치면 표본 부족이 "채점기 회귀"로 읽히고, 자연스러운 처방은 `--n-*`를
# 낮추는 것이 된다 — 그런데 그 수치는 오검출 상한 0.02 규약에서 **역산된 값**이라(n=100이면
# 0건이어도 상한 0.026으로 규약을 증명하지 못한다) 낮추는 순간 게이트가 공허해진다.
# 즉 신호를 구분하지 않으면 가장 그럴듯한 오답이 게이트를 망가뜨리는 쪽이다.
# 선례: `ops/live_preflight.py`의 `_EXIT_ERROR = 2`("조용히 대체하지 않고 측정 실패로 표면화").
_EXIT_UNMEASURABLE = 2

# 무결함 오검출(정답을 오답으로 오판) Wilson 상한의 프로젝트 규약 초기값 —
# `docs/standards/superhuman_verification_standard.md` §2 S5("보증된 오류 상한 ≤ 2%").
# **문헌값이 아니라 프로젝트 규약 채용**이며(REC-08 acceptance③), 리포트가 그 사실을 표기한다.
# 검출률 하한보다 엄격한 이유: 오검출은 *맞은 학생을 틀렸다고 판정*하는 것이라 의사결정
# 우선순위 #1(학생 안전·웰빙)에 직접 닿는다(미검출은 클라 보고로 폴백되어 무해).
FALSE_ALARM_UPPER_CONVENTION: float = 0.02

# A버킷 정규화 화이트리스트 — 전각 영숫자(U+FF10-FF19 숫자·U+FF21-FF3A 대문자·U+FF41-FF5A
# 소문자)만 반각으로 접는다. NFKC 전체는 의미를 변형하므로 금지(모듈 docstring).
_FULLWIDTH_OFFSET = 0xFEE0
_FULLWIDTH_RANGES: tuple[tuple[int, int], ...] = (
    (0xFF10, 0xFF19),
    (0xFF21, 0xFF3A),
    (0xFF41, 0xFF5A),
)

SelectiveDefectClass = Literal["answer_shift", "distractor_substitution"]
"""주입 결함 2종 — `answer_shift`(정답 수치 오기·B버킷) ·
`distractor_substitution`(오답 선지 치환·A버킷)."""

SELECTIVE_DEFECT_CLASSES: tuple[SelectiveDefectClass, ...] = get_args(SelectiveDefectClass)

SelectiveGrade = Literal["correct", "incorrect", "undecidable"]
"""채점 3상태 — `undecidable`은 오답이 아니다(교수학 금기 승계)."""


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 로드 (hermetic — DB 0·네트워크 0, CI에서 그대로 실행 가능)
# ──────────────────────────────────────────────────────────────────────────
def _repo_root() -> Path:
    # src/backend/whymath_backend/harness/ → repo root 4단계 위(crosslink_demotion_eval 동형).
    return Path(__file__).resolve().parents[4]


def load_corpus_problems(paths: Sequence[Path] | None = None) -> list[Problem]:
    """코퍼스 JSONL 전량 → `Problem` 목록(결정론·파일명 정렬·DB 0).

    `license`·`concepts` 등 **Problem 스키마 밖 저작 메타**는 `_AUTHORING_KEYS`로 분리한다
    (`l1/problem_bank/populate.py`가 세운 단일 원천 — `extra="forbid"` 대응 로직 재구현 0).
    """
    targets = (
        sorted((_repo_root() / "data" / "corpus").glob("problem_bank_*/problems.jsonl"))
        if paths is None
        else list(paths)
    )
    problems: list[Problem] = []
    for path in targets:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            data = {k: v for k, v in raw.items() if k not in _AUTHORING_KEYS}
            problems.append(Problem.model_validate(data))
    return problems


# ──────────────────────────────────────────────────────────────────────────
# 시더 — 결함 주입이 곧 정답지(GT)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class SelectiveTrial:
    """강등전 1건 — (문항, 학생 제출 시뮬레이션, 주입 결함). `defect_class=None`이면 무결함.

    `submitted_answer`는 무결함이면 정답 그대로, 결함이면 변조값이다 — 즉 **기대 채점 결과가
    주입 사실로 확정**된다(무결함→correct 기대·결함→incorrect 기대).
    """

    slug: str
    bucket: GradabilityBucket
    correct_answer: str
    submitted_answer: str
    defect_class: SelectiveDefectClass | None
    mutation_note: str = ""


def _shift_numeric_answer(answer: str) -> tuple[str, str] | None:
    """정답 수치 +1(B버킷 결함) — 파싱 불가면 `None`(조용한 무변조 금지 · 호출자가 건너뛴다)."""
    try:
        shifted = Fraction(answer.strip()) + 1
    except (ValueError, ZeroDivisionError):
        return None
    new = (
        str(shifted.numerator)
        if shifted.denominator == 1
        else f"{shifted.numerator}/{shifted.denominator}"
    )
    return new, f"answer {answer!r} → {new!r} (+1)"


def _substitute_distractor(problem: Problem, rng: random.Random) -> tuple[str, str] | None:
    """정답이 아닌 선지로 치환(A버킷 결함) — 오답 선지가 없으면 `None`."""
    correct = (problem.answer or "").strip()
    distractors = [c for c in (problem.choices or []) if c.strip() != correct]
    if not distractors:
        return None
    picked = distractors[rng.randrange(len(distractors))]
    return picked, f"answer {correct!r} → distractor {picked!r}"


class InsufficientPoolError(ValueError):
    """버킷 풀이 요청 표본을 못 채운다 — 기준 미달이 아니라 **판정 불가**다(NLP-10).

    `ValueError`를 상속하는 이유는 호출자 호환이다(기존 계약은 "풀이 모자라면 ValueError").
    타입을 따로 두는 이유는 `main()`이 이 실패만 exit 2로 갈라내기 위해서다 — 코퍼스 파싱
    오류와 표본 부족을 같은 코드로 내면 무엇을 고쳐야 하는지가 사라진다.
    """

    def __init__(self, bucket: str, available: int) -> None:
        self.bucket = bucket
        self.available = available
        super().__init__(
            f"{bucket} 풀 소진 — 요청 수를 줄이거나 코퍼스를 늘려야 한다(가용 {available}건)."
        )


@dataclass(frozen=True)
class BucketHeadroom:
    """한 버킷의 표본 수급 — 가용·최소 요구·여유(NLP-10 acceptance①②)."""

    bucket: GradabilityBucket
    available: int
    required: int

    @property
    def headroom(self) -> int:
        return self.available - self.required

    @property
    def sufficient(self) -> bool:
        return self.headroom >= 0

    @property
    def tight(self) -> bool:
        """여유가 요구량의 `_HEADROOM_WARN_RATIO` 미만인가 — 아직 되지만 곧 안 될 상태."""
        return self.sufficient and self.headroom < self.required * _HEADROOM_WARN_RATIO


# 여유 경고선 — 요구 표본의 10%.
#
# 임의값이 아니라 "다음 한 번의 분류 개선이 게이트를 깨뜨릴 수 있는가"를 대략 재는 선이다.
# NLP-09 한 건이 B버킷을 7,130 → 154로 줄였고(요구 150 · 여유 4 = 2.7%), 그 변경은 게이트를
# 깨뜨리려는 의도가 전혀 없는 정상 개선이었다. 경고가 없으면 다음 개선은 예고 없이 깬다.
_HEADROOM_WARN_RATIO = 0.10


def _bucket_demand(n_defective: int, n_clean: int) -> dict[GradabilityBucket, int]:
    """버킷별 **최소** 요구 표본 수 — 아래 셋 구성의 짝/홀 배분과 같은 산식.

    `build_selective_demotion_set`은 index 짝수를 A, 홀수를 B에 배정하고, 결함 단계와
    무결함 단계가 **커서를 공유**한다(같은 문항을 두 번 쓰지 않는다). 그래서 한 버킷의
    총 소비는 `결함분 + 무결함분`이다 — 이 합산을 빠뜨리면 여유를 2배로 착각한다.

    "최소"인 이유: 결함 단계는 변조 불가 문항을 건너뛰므로(무변조 결함 trial 금지) 실제
    소비가 이보다 클 수 있다. 그러므로 이 값으로 충분하다고 판정하지 않는다 — 실제 부족은
    `InsufficientPoolError`가 잡고, 이 값은 *경고와 진단*을 위한 하한선이다.
    """
    demand: dict[GradabilityBucket, int] = {
        "selectable_exact_match": 0,
        "numeric_short_answer_candidate": 0,
    }
    for total in (n_defective, n_clean):
        for index in range(total):
            key: GradabilityBucket = (
                "selectable_exact_match" if index % 2 == 0 else "numeric_short_answer_candidate"
            )
            demand[key] += 1
    return demand


def bucket_headroom(
    problems: Sequence[Problem], *, n_defective: int, n_clean: int
) -> list[BucketHeadroom]:
    """버킷별 표본 수급을 잰다 — 셋을 만들기 **전에** 판정 가능성을 확인하기 위함.

    풀 산정 조건은 `build_selective_demotion_set`과 같아야 한다(`answer`·`slug` 보유).
    다르면 "여유 있다고 했는데 터진다"가 되어 경고 자체가 위장이 된다.
    """
    demand = _bucket_demand(n_defective, n_clean)
    available: dict[GradabilityBucket, int] = dict.fromkeys(demand, 0)
    for problem in problems:
        classified = classify_gradability(problem)
        if classified in available and problem.answer and problem.slug:
            # `classify_gradability`가 이미 `GradabilityBucket`을 반환한다 — cast는 중복이고
            # mypy strict의 `redundant-cast`가 이를 오류로 낸다(CI 실측 2026-09-10).
            available[classified] += 1
    return [
        BucketHeadroom(bucket=bucket, available=available[bucket], required=demand[bucket])
        for bucket in demand
    ]


def format_headroom(rows: Sequence[BucketHeadroom]) -> str:
    """표본 수급을 항상 낸다 — 0건도 값으로 읽히게(CLAUDE.md 분모 표기 원칙)."""
    lines = ["[표본 수급 — 버킷별 가용/요구]"]
    for row in rows:
        mark = "✔" if row.sufficient else "✖"
        note = " ← 여유 부족(곧 판정 불가)" if row.tight else ""
        lines.append(
            f"  {mark} {row.bucket:<32} 가용 {row.available:>5} · 최소요구 {row.required:>4}"
            f" · 여유 {row.headroom:>+5}{note}"
        )
    return "\n".join(lines)


def build_selective_demotion_set(
    problems: Sequence[Problem],
    *,
    n_defective: int = 100,
    n_clean: int = 100,
    seed: int = 20260810,
) -> list[SelectiveTrial]:
    """A/B 버킷에서 결함·무결함 trial을 균형 있게 산출(결정론·런타임·커밋 0).

    버킷 배분은 결함·무결함 각각 A/B 절반씩이다(한쪽 버킷만으로 게이트가 통과되지 않게).
    모집단은 `classify_gradability`가 확정한다 — REC-05와 같은 정의를 재사용(재정의 0).
    풀이 모자라면 `ValueError`(조용한 부분 셋 반환 금지 — `defect_seeder.py` 관례).
    """
    rng = random.Random(seed)
    by_bucket: dict[GradabilityBucket, list[Problem]] = {
        "selectable_exact_match": [],
        "numeric_short_answer_candidate": [],
    }
    for problem in problems:
        classified = classify_gradability(problem)
        if classified in by_bucket and problem.answer and problem.slug:
            by_bucket[classified].append(problem)
    for pool in by_bucket.values():
        pool.sort(key=lambda p: p.slug or "")  # 파일 순서 비의존(결정론)
        rng.shuffle(pool)

    trials: list[SelectiveTrial] = []
    cursor: dict[GradabilityBucket, int] = dict.fromkeys(by_bucket, 0)

    def _take(bucket: GradabilityBucket) -> Problem:
        index = cursor[bucket]
        pool = by_bucket[bucket]
        if index >= len(pool):
            raise InsufficientPoolError(bucket, len(pool))
        cursor[bucket] = index + 1
        return pool[index]

    # ── 결함 trial: A는 오답 선지 치환, B는 정답 수치 오기 ──
    for index in range(n_defective):
        bucket: GradabilityBucket = (
            "selectable_exact_match" if index % 2 == 0 else "numeric_short_answer_candidate"
        )
        while True:
            problem = _take(bucket)
            correct = (problem.answer or "").strip()
            mutated = (
                _substitute_distractor(problem, rng)
                if bucket == "selectable_exact_match"
                else _shift_numeric_answer(correct)
            )
            if mutated is not None:
                break  # 변조 불가 문항은 건너뛰고 다음 후보로(무변조 결함 trial 금지)
        submitted, note = mutated
        trials.append(
            SelectiveTrial(
                slug=problem.slug or "",
                bucket=bucket,
                correct_answer=correct,
                submitted_answer=submitted,
                defect_class=(
                    "distractor_substitution"
                    if bucket == "selectable_exact_match"
                    else "answer_shift"
                ),
                mutation_note=note,
            )
        )

    # ── 무결함 trial: 정답을 그대로 제출 ──
    for index in range(n_clean):
        bucket = "selectable_exact_match" if index % 2 == 0 else "numeric_short_answer_candidate"
        problem = _take(bucket)
        correct = (problem.answer or "").strip()
        trials.append(
            SelectiveTrial(
                slug=problem.slug or "",
                bucket=bucket,
                correct_answer=correct,
                submitted_answer=correct,
                defect_class=None,
            )
        )

    rng.shuffle(trials)  # 결함/무결함이 순서로 드러나지 않게
    return trials


# ──────────────────────────────────────────────────────────────────────────
# 비교기 — shadow 전용(라이브 요청 경로 무영향)
# ──────────────────────────────────────────────────────────────────────────
def normalize_choice_answer(text: str) -> str:
    """A버킷 안전 정규화 — 양끝 공백 제거 + 내부 공백 축약 + 전각 영숫자만 반각으로.

    **NFKC를 쓰지 않는다**: NFKC는 `③`→`3`(선지 라벨→선지 값)·`x²`→`x2`(지수 파괴)로 의미를
    변형해 acceptance②("의미 변형 정규화 0")를 위반한다. 여기서 접는 것은 표기 폭(전각/반각)과
    공백뿐이며 문자 의미는 보존된다.
    """
    folded = "".join(
        (
            chr(ord(ch) - _FULLWIDTH_OFFSET)
            if any(low <= ord(ch) <= high for low, high in _FULLWIDTH_RANGES)
            else ch
        )
        for ch in text
    )
    return " ".join(folded.split())


def _is_numeric_expression(text: str) -> bool:
    """SymPy가 이 문자열을 *수*로 읽는가 — 비수치 정답은 채점 대상이 아님을 확정.

    선례: `l3/pregenerate/validator.py`·`l3/solution_set.py`가 같은 `is_number` 게이트를 쓴다.
    """
    try:
        parsed = sympy.sympify(text)
    except Exception:  # noqa: BLE001 — 파싱 불가는 "수치 아님"(보수적·pass 위장 금지)
        return False
    return bool(getattr(parsed, "is_number", False))


def grade_selective(trial: SelectiveTrial) -> SelectiveGrade:
    """trial 1건 → 채점 3상태(순수·결정론·DB 0).

    - **A버킷**: 화이트리스트 정규화 후 정확일치 → `correct`/`incorrect`(판정 불가 없음 —
      선지 문자열 비교는 항상 결정된다).
    - **B버킷**: `identity_status(제출, 정답)` 4상태를 3상태로 접는다 — `identity`→`correct`,
      `not_identity`→`incorrect`, `undecidable`/`parse_error`→`undecidable`.
      정답이 수치로 읽히지 않으면 채점 자체를 시도하지 않는다(`undecidable`).

    `undecidable`은 **오답이 아니다** — 호출자(집계)가 검출로도 오검출로도 세지 않는다.
    """
    if trial.bucket == "selectable_exact_match":
        submitted = normalize_choice_answer(trial.submitted_answer)
        correct = normalize_choice_answer(trial.correct_answer)
        return "correct" if submitted == correct else "incorrect"

    if not _is_numeric_expression(trial.correct_answer):
        return "undecidable"
    verdict = identity_status(trial.submitted_answer, trial.correct_answer)
    if verdict is IdentityVerdict.identity:
        return "correct"
    if verdict is IdentityVerdict.not_identity:
        return "incorrect"
    return "undecidable"


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 검출률 하한 / 오검출 상한 (defect_detection_eval 형태 승계)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class SelectiveDemotionReport:
    """강등전 집계 — 버킷별 검출 + 전체 검출률 Wilson 하한 + 무결함 오검출 Wilson 상한.

    `undecidable_*`는 검출·오검출 어느 쪽에도 계상되지 않는 **제3 버킷**이다(교수학 금기).
    분모에는 남으므로 undecidable이 많으면 검출률 하한이 정직하게 내려간다 — "대부분 모른다고
    답해 오검출을 피하는" 채점기가 게이트를 통과하지 못하게 하는 장치다.
    """

    per_bucket: dict[str, tuple[int, int]]  # bucket → (detected, defective_total)
    defective_detected: int
    defective_total: int
    false_alarm: int
    clean_total: int
    undecidable_defective: int
    undecidable_clean: int

    def detection_lower_bound(self, confidence: float = 0.95) -> float | None:
        """결함 검출률의 Wilson 단측 하한 — 결함 표본 0이면 `None`(분모 없는 0 금지)."""
        if self.defective_total == 0:
            return None
        return wilson_lower_bound(self.defective_detected, self.defective_total, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float | None:
        """무결함 오검출률의 Wilson 단측 상한 — 무결함 표본 0이면 `None`."""
        if self.clean_total == 0:
            return None
        return wilson_upper_bound(self.false_alarm, self.clean_total, confidence)

    def to_json(self) -> dict[str, Any]:
        return {
            "per_bucket": {k: list(v) for k, v in self.per_bucket.items()},
            "defective_detected": self.defective_detected,
            "defective_total": self.defective_total,
            "false_alarm": self.false_alarm,
            "clean_total": self.clean_total,
            "undecidable_defective": self.undecidable_defective,
            "undecidable_clean": self.undecidable_clean,
            "detection_lower_bound": self.detection_lower_bound(),
            "false_alarm_upper_bound": self.false_alarm_upper_bound(),
        }


def summarize(trials: Sequence[SelectiveTrial]) -> SelectiveDemotionReport:
    """trial 목록 → 강등전 집계(순수·부작용 0).

    결함 trial: 채점이 `incorrect`면 **검출**(주입한 오답을 오답이라 했다). `undecidable`은
    미검출로 계상한다(보수적 — 모른다고 답한 것은 잡은 게 아니다).
    무결함 trial: 채점이 `incorrect`면 **오검출**(맞은 학생을 틀렸다고 했다). `undecidable`은
    오검출이 아니다(학생 무해 — 오답으로 강등하지 않는다).
    """
    per_bucket: dict[str, list[int]] = {
        b: [0, 0] for b in ("selectable_exact_match", "numeric_short_answer_candidate")
    }
    defective_detected = defective_total = false_alarm = clean_total = 0
    undecidable_defective = undecidable_clean = 0

    for trial in trials:
        grade = grade_selective(trial)
        if trial.defect_class is not None:
            defective_total += 1
            slot = per_bucket.setdefault(trial.bucket, [0, 0])
            slot[1] += 1
            if grade == "incorrect":
                defective_detected += 1
                slot[0] += 1
            elif grade == "undecidable":
                undecidable_defective += 1
        else:
            clean_total += 1
            if grade == "incorrect":
                false_alarm += 1
            elif grade == "undecidable":
                undecidable_clean += 1

    return SelectiveDemotionReport(
        per_bucket={k: (v[0], v[1]) for k, v in per_bucket.items()},
        defective_detected=defective_detected,
        defective_total=defective_total,
        false_alarm=false_alarm,
        clean_total=clean_total,
        undecidable_defective=undecidable_defective,
        undecidable_clean=undecidable_clean,
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_report(report: SelectiveDemotionReport, *, confidence: float) -> str:
    """사람 가독 리포트 — 버킷별 검출 + 전체 경계 + 판정 불가 회계 + 임계 근거 정직 표기."""
    pct = round(confidence * 100)
    lines = [
        "=" * 68,
        "강등전 — 선택형·수치 단답 서버 채점 (REC-08 · 초인간 검증 §3)",
        "=" * 68,
        "> 관측·게이트 전용이다 — 이 게이트가 PASS해도 채점 권위는 이관되지 않는다",
        ">   (클라 배선·attempt 입력 소비·is_correct 대체 0). PASS/FAIL은 REC-07의 입력이다.",
        "",
        "[버킷별 결함 검출]",
    ]
    for bucket, (detected, total) in sorted(report.per_bucket.items()):
        rate = _fmt(detected / total) if total else "n/a"
        flag = "  ← 미검출(공백)" if total and detected == 0 else ""
        lines.append(f"  {bucket:32s} {detected:>3d}/{total:<3d}  ({rate}){flag}")

    dlb = report.detection_lower_bound(confidence)
    fau = report.false_alarm_upper_bound(confidence)
    point = report.defective_detected / report.defective_total if report.defective_total else None
    lines.append("[전체]")
    lines.append(
        f"  결함 검출률   : {report.defective_detected}/{report.defective_total} "
        f"(점추정 {_fmt(point)}·{pct}% 하한 {_fmt(dlb)})"
    )
    lines.append(
        f"  무결함 오검출 : {report.false_alarm}/{report.clean_total} ({pct}% 상한 {_fmt(fau)}) "
        "— 맞은 학생을 틀렸다고 판정한 비율(학생 안전 축)"
    )
    lines.append("[판정 불가 회계 — 검출·오검출 어느 쪽에도 계상되지 않음]")
    lines.append(
        f"  결함 trial 중 undecidable : {report.undecidable_defective} "
        "(미검출로 계상 — 모른다고 답한 것은 잡은 게 아니다)"
    )
    lines.append(
        f"  무결함 trial 중 undecidable: {report.undecidable_clean} (오검출 아님 — 학생 무해)"
    )
    lines.append("[임계 근거]")
    lines.append(
        f"  오검출 상한 규약값 {FALSE_ALARM_UPPER_CONVENTION} — 문헌값이 아니라 "
        "superhuman_verification_standard.md §2 S5(≤2%) 프로젝트 규약 채용(미보정)."
    )
    lines.append("=" * 68)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# CLI — exit 0(통과)/1(게이트 미달). 임계는 opt-in 센티널(기본 off).
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """강등전 CLI — 코퍼스 로드 → 결함 셋 산출 → 채점 → Wilson 경계 판정."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.selective_grading_demotion_eval",
        description=(
            "선택형·수치 단답 서버 채점의 결함 주입 강등전 — 검출률 Wilson 하한·무결함 오검출 "
            "Wilson 상한 측정(REC-08·권위 이관 0·hermetic)."
        ),
    )
    parser.add_argument("--n-defective", type=int, default=100, help="결함 trial 수(기본 100).")
    parser.add_argument("--n-clean", type=int, default=100, help="무결함 trial 수(기본 100).")
    parser.add_argument("--seed", type=int, default=20260810, help="셋 생성 시드(결정론).")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 신뢰수준(단측).")
    parser.add_argument(
        "--min-detection-lower",
        type=float,
        default=0.0,
        help="결함 검출률 Wilson 하한 임계 — 미만이면 exit 1(기본 0=off).",
    )
    parser.add_argument(
        "--max-false-alarm-upper",
        type=float,
        default=1.0,
        help="무결함 오검출 Wilson 상한 임계 — 초과면 exit 1(기본 1.0=off).",
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)."
    )
    args = parser.parse_args(argv)

    try:
        problems = load_corpus_problems()
    except Exception as exc:  # noqa: BLE001 — 코퍼스를 못 읽으면 잰 것이 없다(측정 실패)
        print(f"코퍼스 적재 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_UNMEASURABLE

    # 표본 수급을 **셋 구성 전에** 낸다 — 터진 뒤에 보이면 진단이지 예방이 아니다(NLP-10).
    headroom = bucket_headroom(problems, n_defective=args.n_defective, n_clean=args.n_clean)
    print(format_headroom(headroom))
    for row in headroom:
        if row.tight:
            sys.stderr.write(
                f"[표본 여유 부족] {row.bucket} — 가용 {row.available} · 최소요구 "
                f"{row.required} · 여유 {row.headroom}. 아직 판정은 되지만, 분류가 조금만 더 "
                "정확해지면 이 게이트는 통과가 아니라 판정 불가가 된다(NLP-10)\n"
            )

    try:
        trials = build_selective_demotion_set(
            problems, n_defective=args.n_defective, n_clean=args.n_clean, seed=args.seed
        )
    except InsufficientPoolError as exc:
        # 기준 미달이 아니라 **판정 불가**다 — 처방이 다르므로 종료 코드도 다르다.
        print(
            f"[표본 부족 — 판정 불가] {exc}\n"
            "  이것은 게이트 실패가 아니다(통과도 아니다). 채점기를 의심하기 전에 표본을 본다.\n"
            f"  --n-defective/--n-clean을 낮추지 말 것 — 그 수치는 오검출 상한 "
            f"{FALSE_ALARM_UPPER_CONVENTION} 규약에서 역산된 값이라 낮추면 게이트가 공허해진다.\n"
            "  해소: 이 버킷의 모집단을 늘리거나(코퍼스·분류 정의) 표본 배분을 재설계한다.",
            file=sys.stderr,
        )
        return _EXIT_UNMEASURABLE
    except Exception as exc:  # noqa: BLE001 — 그 밖의 셋 구성 실패도 잰 것이 없다
        print(f"셋 구성 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_UNMEASURABLE

    report = summarize(trials)
    print(format_report(report, confidence=args.confidence))

    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"JSON 산출물: {args.json_path}")

    # 게이트(opt-in) — 검출률 하한 미달 또는 오검출 상한 초과면 exit 1.
    # `None`(표본 0)도 실패다 — 무측정을 통과로 위장하지 않는다.
    exit_code = _EXIT_OK
    dlb = report.detection_lower_bound(args.confidence)
    if args.min_detection_lower > 0.0 and (dlb is None or dlb < args.min_detection_lower):
        exit_code = _EXIT_GATE_FAIL
    fau = report.false_alarm_upper_bound(args.confidence)
    if args.max_false_alarm_upper < 1.0 and (fau is None or fau > args.max_false_alarm_upper):
        exit_code = _EXIT_GATE_FAIL
    return exit_code


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
