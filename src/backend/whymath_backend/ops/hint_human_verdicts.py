"""힌트 정답 누설 — 사람 판정 기록 좌석·표본 매니페스트·의미 축 계산 (EOS-210).

왜 이 모듈이 있는가
------------------
G3 조건 "힌트 의미 누설 0"을 재는 `ops/g3_content_measures`(EOS-207)는 L1·L2 힌트의 정답 누설을
**기계 두 축**(글자·값)으로만 판정한다. 남는 구멍이 둘이다.

  (가) **기계 판정 불가** — 짧은 정답의 글자 축 유보·값 축 판정 불가 힌트는 사람 폴백(`None`)으로
       남아 측정기가 `UNDECIDED`(exit 2)를 낸다. 그 힌트를 누가 판정해 어디에 적는지가 없었다.
  (나) **의미적 누설** — 표준 `docs/standards/eos_verification_design_v1.md` §5 F-Ⅴ가 "힌트의
       의미적 정답 누설(**자동 검사 밖**)"을 표본 검수로 재라고 했고, §6이 "전수 자동 + LLM 심판 +
       **인간 30건**"을 요구한다. 측정기는 그래서 `HINT_SEMANTIC_AXIS=NOT_MEASURED`를 항상 냈다.

이 모듈이 두 구멍의 **기록 계약**과 **표본 계약**, 그리고 의미 축의 산술을 정한다. 기록을 받는
도구는 `harness/hint_verdict_session`(맹검 검수 CLI), 기록을 읽는 쪽은 측정기다.

판정 기록 계약 — `hint_verdicts.jsonl` (1행 1판정 · append 전용)
--------------------------------------------------------------
`HintHumanVerdict` 모델 JSON 1행. 헌법 R2-03(게이트 기록 4요건 — 판정자·일시·근거·우회 여부)의
이 좌석 대응:

  - 판정자   = `reviewer`     — 이름이 아니라 Kiki가 정하는 짧은 ID(ASCII 1~32자 · 개인정보 최소화)
  - 일시     = `judged_at`    — UTC(오프셋 0이 아니면 거부)
  - 근거     = `rationale`    — 사람이 적은 판정 이유(공백뿐이면 거부)
               + `content_fingerprint` — 판정자에게 **보인 내용**(문항·선택지·정답·힌트 단계·본문)의
               지문. 판정 뒤 힌트·정답이 바뀌면 측정기가 그 판정을 낡음(stale)으로 빼고 센다.
  - 우회 여부 = `bypassed`    — True = 맹검 도구(R19-01)를 거치지 않고 기입된 판정. 도구는 항상
               False를 쓴다. True 행은 **어느 축에도 계상하지 않고** 따로 센다. 기본값이 없다 —
               손으로 쓴 행이 필드를 빼먹어 "우회 아님"으로 조용히 채워지지 않게 한다.

나머지: `hint_id`·`problem_id`(힌트의 문제와 다르면 측정 실패) · `verdict`(`leaked`/`not_leaked`) ·
`purpose`(`machine_undecided`/`semantic_sample` — **물은 이유**. 두 목적이 겹치는 힌트는 한 번만
묻고 `semantic_sample`로 적는다. 사람 판정은 힌트에 대한 것이지 목적에 대한 것이 아니므로 (가)의
해소는 목적과 무관하게 그 힌트의 최신 판정을 쓴다) · `sample_id`(매니페스트 식별자) ·
`review_session_id`.

**재판정은 덮어쓰지 않는다.** 같은 `hint_id`의 행이 여럿이면 `judged_at`이 가장 늦은 행(동률이면
파일에서 뒤의 행)을 쓰고, 앞선 행은 지우지 않은 채 `superseded`·판정이 뒤집힌 수(`flipped`)로 센다.

**손상은 측정 실패다.** JSON 파싱 실패·필수 필드 누락·잘못된 verdict·빈 근거는 줄 번호와 예외
타입명(필드값 제외)을 오류로 남기고, 측정기는 그 오류를 입력 오류로 올린다(exit 2). 못 읽은
줄을 조용히 건너뛰면 "누설" 판정 하나가 사라진 채 통과가 나올 수 있다.

표본 매니페스트 — 사후 바꿔치기 금지
----------------------------------
(나)의 표본은 **선택 자유가 0**이 되게 정한다:

  - 모집단 = 회차 CU에 붙는(`problem_id` 조인) **verified L1·L2 힌트**. 각 힌트의 내용 지문까지
    묶어 `population_digest`(sha256)를 만든다.
  - seed = `sha256(round_id | population_digest)`의 앞 64비트. 사람이 고르지 않는다 — 고를 수
    있으면 "깨끗해 보이는 표본"이 나올 때까지 다시 뽑을 수 있다.
  - 표본 = 정렬한 모집단에서 `random.Random(seed).sample(·, min(size, 모집단))`. 기본 30건,
    모집단이 30 미만이면 전수(측정기는 그래도 "30건 미만 → 측정 불가"를 그대로 적용한다).
  - `sample_id` = `round_id | population_digest | size`의 지문.

매니페스트는 위 셋을 **자기 검증**한다(seed·표본·digest·sample_id를 다시 계산해 다르면 거부). 그래서
파일을 손으로 고쳐 표본 hint_id를 바꾸면 읽기 단계에서 걸린다. 측정기는 여기에 더해 매니페스트의
모집단을 **현재 입력**에서 다시 계산한 모집단과 대조한다(힌트가 바뀌었으면 측정 실패).

(가)의 대상(기계 판정 불가)은 표본과 **별개로 전수**이며 `machine_undecided_hint_ids`에 싣는다.

의미 축 — n·k·Wilson 단측 95% 상한
--------------------------------
매니페스트 표본의 hint_id 중 **그 매니페스트의 `sample_id`로 기록된** 유효 판정만 센다. 표본 밖
판정은 의미 축에 넣지 않고 `outside_manifest`로 따로 센다(사후에 고른 힌트로 표본을 채우지 못하게).

  - n = 판정된 표본 수 · k = 그중 누설(사람 `leaked` **또는** 기계 누설 — 기계 누설은 사람
    판정으로 뒤집지 않는다).
  - k > 0                → FAIL(무관용 — "누설 0" 조건)
  - 표본 미판정이 남음    → NOT_MEASURABLE(판정자가 어려운 힌트만 건너뛰면 그것도 고르기다)
  - n < 30               → NOT_MEASURABLE(0건 통과 위장 금지)
  - k = 0 · n ≥ 30       → PASS + **Wilson 상한 공개**(0/30이어도 상한은 약 8.3% — 숨기지 않는다)

비대칭 하나: 표본 밖에서라도 사람이 **누설을 확인**한 L1·L2 힌트(기계 clean)는 축을 FAIL로 만든다.
표본 밖 판정을 빼는 이유는 낙관 쪽 고르기를 막는 것인데, 확인된 누설을 숨기는 쪽으로 같은 규칙을
쓰면 학생 안전(의사결정 우선순위 1)을 깎는다.

이 모듈은 I/O를 판정 기록·매니페스트 파일 읽기/쓰기로만 한정하고, 기계 누설 판정은 하지 않는다
(그건 측정기 몫 — 여기서는 호출자가 넘긴 판정을 쓴다).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l4.hint_content.models import Hint

__all__ = [
    "DEFAULT_SAMPLE_SIZE",
    "MANIFEST_SCHEMA",
    "RATIONALE_MAX_LENGTH",
    "REVIEWER_ID_PATTERN",
    "SEMANTIC_MIN_SAMPLE",
    "VERDICT_SCHEMA",
    "HintHumanVerdict",
    "HintVerdict",
    "HintVerdictPurpose",
    "LatestVerdicts",
    "SampleManifest",
    "SemanticAxis",
    "append_verdict",
    "build_manifest",
    "derive_sample_id",
    "derive_seed",
    "draw_sample",
    "hint_review_fingerprint",
    "latest_verdicts",
    "load_manifest",
    "load_verdicts",
    "measure_semantic_axis",
    "population_digest",
    "review_view",
    "sample_population",
    "write_manifest",
]

VERDICT_SCHEMA = "hint-human-verdict/v1"
MANIFEST_SCHEMA = "hint-verdict-sample-manifest/v1"
DEFAULT_SAMPLE_SIZE = 30
SEMANTIC_MIN_SAMPLE = 30  # §6 "인간 30건" — 미만이면 측정 불가
RATIONALE_MAX_LENGTH = 2000
# 판정자 ID — 이름·연락처가 아니라 짧은 식별자(ASCII 영숫자로 시작 · 1~32자 · `_.-` 허용).
REVIEWER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$"
_FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SAMPLE_ID_PATTERN = r"^hvs-[0-9a-f]{16}$"
_ZERO_TOLERANCE_LEVELS: frozenset[int] = frozenset({1, 2})


class HintVerdict(StrEnum):
    """사람 판정 — 누설/아님 2값. '모르겠다'는 기록하지 않는다(판정하지 않으면 행이 없다)."""

    LEAKED = "leaked"
    NOT_LEAKED = "not_leaked"


class HintVerdictPurpose(StrEnum):
    """물은 이유 — (가) 기계 판정 불가 전수 · (나) 의미 누설 표본."""

    MACHINE_UNDECIDED = "machine_undecided"
    SEMANTIC_SAMPLE = "semantic_sample"


# ──────────────────────────────────────────────────────────────────────────
# 판정자에게 보이는 내용 — 렌더와 지문이 같은 dict를 쓴다(보인 것 = 지문 건 것)
# ──────────────────────────────────────────────────────────────────────────
def review_view(cu_row: Mapping[str, Any], hint: Hint) -> dict[str, Any]:
    """판정자에게 보여 줄 내용(문항·선택지·정답·힌트 단계·본문) — **기계 판정은 넣지 않는다**.

    `Hint.gate_report`(게이트 판정)·`reveals`(선언 노출량)는 제외한다(R19-01 — 사람 입력 전 AI 참고
    판정 비노출). 정답은 넣는다 — 정답을 알아야 누설을 판정할 수 있다.
    """
    question = cu_row.get("question_text")
    if not isinstance(question, str) or not question.strip():
        alt = cu_row.get("question_text_md")
        question = alt if isinstance(alt, str) and alt.strip() else None
    answer = cu_row.get("answer")
    choices = cu_row.get("choices")
    return {
        "question_text": question,
        "choices": choices if isinstance(choices, list) and choices else None,
        "answer": answer if isinstance(answer, str) else None,
        "hint_level": int(hint.level),
        "hint_content": hint.content,
    }


def hint_review_fingerprint(cu_row: Mapping[str, Any], hint: Hint) -> str:
    """`review_view`의 지문 — 키 정렬·한글 그대로·최소 구분자 JSON → sha256."""
    canonical = json.dumps(
        review_view(cu_row, hint), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# 판정 기록
# ──────────────────────────────────────────────────────────────────────────
class HintHumanVerdict(BaseModel):
    """사람 판정 1건(모듈 docstring '판정 기록 계약'). 필드는 전부 필수다(기본값 없음)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["hint-human-verdict/v1"]
    hint_id: str = Field(min_length=1)
    problem_id: uuid.UUID
    reviewer: str = Field(pattern=REVIEWER_ID_PATTERN)
    judged_at: AwareDatetime
    verdict: HintVerdict
    rationale: str = Field(max_length=RATIONALE_MAX_LENGTH)
    purpose: HintVerdictPurpose
    sample_id: str = Field(pattern=_SAMPLE_ID_PATTERN)
    content_fingerprint: str = Field(pattern=_FINGERPRINT_PATTERN)
    review_session_id: uuid.UUID
    bypassed: bool

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("근거(rationale)가 비었다 — 근거 없는 판정은 기록하지 않는다")
        return value

    @field_validator("judged_at")
    @classmethod
    def _judged_at_is_utc(cls, value: AwareDatetime) -> AwareDatetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("judged_at은 UTC(오프셋 0)여야 한다")
        return value


def load_verdicts(path: Path) -> tuple[list[HintHumanVerdict], list[str]]:
    """판정 JSONL → (판정, 오류). 오류는 줄 번호·예외 타입명·필드 이름만 싣는다(값 제외).

    파일이 없으면 오류 1건이다 — 경로를 줬는데 없는 것은 "판정 0건"이 아니다.
    """
    verdicts: list[HintHumanVerdict] = []
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return verdicts, [f"{path.name} 읽기 실패 — {type(exc).__name__}"]
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_no} JSON 파싱 실패 — {type(exc).__name__}")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{path.name}:{line_no} 객체가 아님({type(parsed).__name__})")
            continue
        try:
            verdicts.append(HintHumanVerdict.model_validate(parsed))
        except ValidationError as exc:
            fields = sorted(
                {".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()}
            )
            errors.append(
                f"{path.name}:{line_no} 판정 계약 위반 — {type(exc).__name__}({', '.join(fields)})"
            )
    return verdicts, errors


def append_verdict(path: Path, verdict: HintHumanVerdict) -> None:
    """판정 1건을 **즉시** append한다(open→write→flush→fsync→close). 실패는 그대로 올린다.

    입력이 이미 검증된 모델이라 쓰기 전 검증은 생성 시점에 끝나 있다. 직렬화 결과를 다시 읽어
    같은 모델로 되돌아오는지까지 확인한다 — 쓴 것이 읽히지 않는 기록은 기록이 아니다.
    """
    line = verdict.model_dump_json()
    if HintHumanVerdict.model_validate_json(line) != verdict:  # pragma: no cover — 방어
        raise ValueError("직렬화 왕복 불일치 — 기록하지 않는다")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(slots=True)
class LatestVerdicts:
    """hint_id → 최신 판정 + 이력 계수(덮어쓴 행은 지우지 않고 센다)."""

    latest: dict[str, HintHumanVerdict] = field(default_factory=dict)
    superseded: int = 0
    flipped: int = 0
    history_counts: dict[str, int] = field(default_factory=dict)


def latest_verdicts(verdicts: Iterable[HintHumanVerdict]) -> LatestVerdicts:
    """같은 hint_id의 여러 판정 중 `judged_at`이 가장 늦은 것(동률이면 뒤의 행)을 고른다."""
    grouped: dict[str, list[tuple[int, HintHumanVerdict]]] = {}
    for order, verdict in enumerate(verdicts):
        grouped.setdefault(verdict.hint_id, []).append((order, verdict))
    result = LatestVerdicts()
    for hint_id, rows in grouped.items():
        rows.sort(key=lambda pair: (pair[1].judged_at, pair[0]))
        result.latest[hint_id] = rows[-1][1]
        result.history_counts[hint_id] = len(rows)
        result.superseded += len(rows) - 1
        if len({v.verdict for _, v in rows}) > 1:
            result.flipped += 1
    return result


# ──────────────────────────────────────────────────────────────────────────
# 표본 — 모집단·seed·추출·매니페스트
# ──────────────────────────────────────────────────────────────────────────
def sample_population(
    cu_rows: Sequence[Mapping[str, Any]], hints: Sequence[Hint]
) -> tuple[dict[str, str], list[str]]:
    """(나)의 모집단 = 회차 CU에 붙는 verified L1·L2 힌트 → {hint_id: 내용 지문}, 오류.

    hint_id 중복은 오류다(어느 행이 판정 대상인지 정할 수 없다).
    """
    rows_by_problem: dict[str, Mapping[str, Any]] = {}
    for row in cu_rows:
        rows_by_problem.setdefault(str(row.get("problem_id")), row)
    population: dict[str, str] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        if hint.hint_id in seen:
            errors.append(f"hint_id 중복 {hint.hint_id} — 판정 대상을 정할 수 없다")
            continue
        seen.add(hint.hint_id)
        cu_row = rows_by_problem.get(str(hint.solution_step_ref.problem_id))
        if cu_row is None or not hint.verified or hint.level not in _ZERO_TOLERANCE_LEVELS:
            continue
        population[hint.hint_id] = hint_review_fingerprint(cu_row, hint)
    return population, errors


def population_digest(population: Mapping[str, str]) -> str:
    """모집단(hint_id·내용 지문 쌍)의 지문 — 정렬 후 직렬화."""
    canonical = json.dumps(sorted(population.items()), ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_seed(round_id: str, digest: str) -> int:
    """seed = sha256(round_id|digest) 앞 64비트 — 사람이 고르지 않는다."""
    return int(hashlib.sha256(f"{round_id}|{digest}".encode()).hexdigest()[:16], 16)


def derive_sample_id(round_id: str, digest: str, size: int) -> str:
    """표본 식별자 — 회차·모집단·요청 크기가 같으면 같다(재추출해도 같은 표본)."""
    return "hvs-" + hashlib.sha256(f"{round_id}|{digest}|{size}".encode()).hexdigest()[:16]


def draw_sample(population_ids: Iterable[str], seed: int, size: int) -> tuple[str, ...]:
    """결정론 추출 — 정렬한 모집단에서 `Random(seed).sample`. 모집단 ≤ size면 전수."""
    if size < 1:
        raise ValueError(f"표본 크기는 1 이상이어야 한다(받은 값 {size})")
    ordered = sorted(population_ids)
    return tuple(random.Random(seed).sample(ordered, k=min(size, len(ordered))))


class SampleManifest(BaseModel):
    """표본 매니페스트 — 읽을 때 seed·표본·digest·sample_id를 스스로 다시 계산해 대조한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["hint-verdict-sample-manifest/v1"]
    sample_id: str = Field(pattern=_SAMPLE_ID_PATTERN)
    round_id: str = Field(min_length=1)
    created_at: AwareDatetime
    seed: int = Field(ge=0)
    size_requested: int = Field(ge=1)
    population_digest: str = Field(pattern=_FINGERPRINT_PATTERN)
    population: dict[str, str]
    sample_hint_ids: tuple[str, ...]
    machine_undecided_hint_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _self_consistent(self) -> SampleManifest:
        digest = population_digest(self.population)
        if digest != self.population_digest:
            raise ValueError("population_digest가 population과 맞지 않는다(모집단 변조)")
        if self.seed != derive_seed(self.round_id, digest):
            raise ValueError("seed가 규칙(round_id|digest)으로 유도한 값과 다르다(seed 선택 금지)")
        if self.sample_id != derive_sample_id(self.round_id, digest, self.size_requested):
            raise ValueError("sample_id가 규칙으로 유도한 값과 다르다")
        if self.sample_hint_ids != draw_sample(self.population, self.seed, self.size_requested):
            raise ValueError("sample_hint_ids가 seed로 다시 뽑은 표본과 다르다(표본 바꿔치기)")
        if len(set(self.machine_undecided_hint_ids)) != len(self.machine_undecided_hint_ids):
            raise ValueError("machine_undecided_hint_ids에 중복이 있다")
        return self

    @property
    def work_hint_ids(self) -> tuple[str, ...]:
        """판정 대상 전체 = 표본 ∪ 기계 판정 불가(겹치면 한 번)."""
        return tuple(sorted(set(self.sample_hint_ids) | set(self.machine_undecided_hint_ids)))

    def purpose_of(self, hint_id: str) -> HintVerdictPurpose:
        """겹치면 표본 목적으로 적는다(모듈 docstring — 해소는 목적과 무관)."""
        if hint_id in self.sample_hint_ids:
            return HintVerdictPurpose.SEMANTIC_SAMPLE
        return HintVerdictPurpose.MACHINE_UNDECIDED


def build_manifest(
    *,
    round_id: str,
    population: Mapping[str, str],
    machine_undecided_hint_ids: Iterable[str],
    size: int = DEFAULT_SAMPLE_SIZE,
    created_at: Any,
) -> SampleManifest:
    """모집단 → 매니페스트(seed·표본은 규칙으로만 정해진다)."""
    digest = population_digest(population)
    seed = derive_seed(round_id, digest)
    return SampleManifest(
        schema_version="hint-verdict-sample-manifest/v1",
        sample_id=derive_sample_id(round_id, digest, size),
        round_id=round_id,
        created_at=created_at,
        seed=seed,
        size_requested=size,
        population_digest=digest,
        population=dict(sorted(population.items())),
        sample_hint_ids=draw_sample(population, seed, size),
        machine_undecided_hint_ids=tuple(sorted(set(machine_undecided_hint_ids))),
    )


def write_manifest(path: Path, manifest: SampleManifest) -> None:
    """매니페스트를 **새 파일로만** 쓴다(`x` 모드 — 이미 있으면 FileExistsError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(manifest.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_manifest(path: Path) -> tuple[SampleManifest | None, list[str]]:
    """매니페스트 JSON → (모델, 오류). 자기 검증 실패도 오류다."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"{path.name} 읽기 실패 — {type(exc).__name__}"]
    try:
        return SampleManifest.model_validate_json(text), []
    except ValidationError as exc:
        messages = sorted({str(err.get("msg", "")) for err in exc.errors()})
        joined = "; ".join(messages)
        return None, [f"{path.name} 매니페스트 계약 위반 — {type(exc).__name__}: {joined}"]


# ──────────────────────────────────────────────────────────────────────────
# 의미 축
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class SemanticAxis:
    """의미 축 결과. `status` ∈ NOT_MEASURED·NOT_MEASURABLE·FAIL·PASS.

    NOT_MEASURED = 매니페스트를 주지 않아 의미 축을 시작하지 않았다(EOS-207과 같은 상태).
    """

    engaged: bool = False
    sample_id: str | None = None
    sample_size: int = 0
    population_size: int = 0
    n: int = 0
    k: int = 0
    unjudged: int = 0
    machine_leak_in_sample: int = 0
    outside_manifest: int = 0
    sample_id_mismatch: int = 0
    human_leaks_outside_sample: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def wilson_upper(self) -> float | None:
        return wilson_upper_bound(self.k, self.n) if self.n > 0 else None

    @property
    def status(self) -> str:
        if not self.engaged:
            return "FAIL" if self.human_leaks_outside_sample else "NOT_MEASURED"
        if self.errors:
            return "NOT_MEASURABLE"
        if self.k or self.human_leaks_outside_sample:
            return "FAIL"
        if self.unjudged or self.n < SEMANTIC_MIN_SAMPLE:
            return "NOT_MEASURABLE"
        return "PASS"

    @property
    def reason(self) -> str:
        outside = len(self.human_leaks_outside_sample)
        if not self.engaged:
            if outside:
                return (
                    f"표본 밖 사람 확인 누설 {outside}건(기계 clean L1·L2) — 확인된 누설은 "
                    "숨기지 않는다"
                )
            return "표본 매니페스트 미지정 — 의미 축은 사람 표본 검수 전용(§5 F-Ⅴ·§6 인간 30건)"
        if self.errors:
            return f"의미 축 입력 오류 {len(self.errors)}건(첫 사유: {self.errors[0]})"
        if self.k or outside:
            return (
                f"의미 누설 — 표본 {self.n}건 중 {self.k}건 · 표본 밖 사람 확인 누설 {outside}건"
                "(무관용)"
            )
        if self.unjudged:
            return (
                f"표본 {self.sample_size}건 중 미판정 {self.unjudged}건 — 표본을 다 보지 않으면 "
                "고른 것과 같다(측정 불가)"
            )
        if self.n < SEMANTIC_MIN_SAMPLE:
            return (
                f"판정 표본 {self.n}건 < {SEMANTIC_MIN_SAMPLE}건 — 측정 불가(0건 통과 위장 금지 · "
                f"모집단 {self.population_size}건)"
            )
        upper = self.wilson_upper
        upper_text = "None" if upper is None else f"{upper:.4f}"
        return f"표본 {self.n}건 누설 0 — Wilson 단측 95% 상한 {upper_text}(0이 아니다)"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "engaged": self.engaged,
            "sample_id": self.sample_id,
            "sample_size": self.sample_size,
            "population_size": self.population_size,
            "n": self.n,
            "k": self.k,
            "unjudged": self.unjudged,
            "machine_leak_in_sample": self.machine_leak_in_sample,
            "wilson_upper_95": self.wilson_upper,
            "outside_manifest": self.outside_manifest,
            "sample_id_mismatch": self.sample_id_mismatch,
            "human_leaks_outside_sample": list(self.human_leaks_outside_sample),
            "errors": list(self.errors),
        }


def measure_semantic_axis(
    *,
    manifest: SampleManifest | None,
    requested: bool = False,
    current_population: Mapping[str, str] | None,
    usable: Mapping[str, HintHumanVerdict],
    machine: Mapping[str, bool | None],
    levels: Mapping[str, int],
    errors: Sequence[str] = (),
) -> SemanticAxis:
    """의미 축(모듈 docstring). `usable`은 낡음·우회·고아를 뺀 hint_id → 최신 판정,
    `machine`은 hint_id → 기계 누설 3상태, `levels`는 hint_id → 레벨이다.

    `current_population`은 현재 입력에서 다시 계산한 모집단 — 매니페스트와 다르면 측정 실패.
    `requested`는 매니페스트를 *요청*했는가다 — 요청했는데 읽지 못했으면(손상·부재) 의미 축은
    NOT_MEASURED로 물러나지 않고 측정 불가가 된다(요청한 측정의 실패를 미측정으로 위장 금지).
    """
    axis = SemanticAxis(engaged=manifest is not None or requested, errors=list(errors))
    if axis.engaged and manifest is None and not axis.errors:
        axis.errors.append("표본 매니페스트를 요청했으나 읽지 못했다")
    sample: frozenset[str] = frozenset()
    if manifest is not None:
        sample = frozenset(manifest.sample_hint_ids)
        axis.sample_id = manifest.sample_id
        axis.sample_size = len(manifest.sample_hint_ids)
        axis.population_size = len(manifest.population)
        if current_population is None or dict(current_population) != manifest.population:
            axis.errors.append(
                "매니페스트 모집단이 현재 힌트 입력에서 다시 계산한 모집단과 다르다 — 힌트·정답이 "
                "바뀌었거나 다른 회차의 매니페스트다"
            )
    undecided_listed = (
        frozenset(manifest.machine_undecided_hint_ids) if manifest is not None else frozenset()
    )
    for hint_id, verdict in usable.items():
        in_sample = hint_id in sample
        if in_sample and verdict.sample_id == axis.sample_id:
            continue  # 아래 표본 루프가 센다
        if in_sample:
            axis.sample_id_mismatch += 1
        elif hint_id in undecided_listed:
            pass  # (가) 전수 대상 — 매니페스트 안의 정당한 판정(의미 축 밖 · 기계 축이 해소에 쓴다)
        elif manifest is not None or verdict.purpose is HintVerdictPurpose.SEMANTIC_SAMPLE:
            axis.outside_manifest += 1  # 매니페스트 어디에도 없는 판정 — 의미 축에 넣지 않는다
        # 확인된 누설은 표본 밖이라도 숨기지 않는다 — 단 기계가 이미 누설/판정 불가로 본 힌트는
        # 기계 축(누설 또는 사람 해소)이 이미 센다(이중 계상 금지).
        if (
            verdict.verdict is HintVerdict.LEAKED
            and levels.get(hint_id) in _ZERO_TOLERANCE_LEVELS
            and machine.get(hint_id) is False
        ):
            axis.human_leaks_outside_sample.append(hint_id)
    for hint_id in sorted(sample):
        judged = usable.get(hint_id)
        if judged is None or judged.sample_id != axis.sample_id:
            axis.unjudged += 1
            continue
        axis.n += 1
        machine_leak = machine.get(hint_id) is True
        if machine_leak:
            axis.machine_leak_in_sample += 1
        if machine_leak or judged.verdict is HintVerdict.LEAKED:
            axis.k += 1
    axis.human_leaks_outside_sample.sort()
    return axis
