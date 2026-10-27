"""미분 오답 서명 독법의 **그림자 관측 수확 · 활성화 판정** CLI (P3-66 · P3-56 승인 후속 ①).

무엇을 하는가
────────────────────────────────────────────────────────────────────────────
`l4_derivative_signature_mode=shadow`로 운영하면 채점 경로가 훑기 1회마다 로거
`whymath.api.attempt_scan_shadow.record`에 JSON 한 줄을 남긴다
(`api/_attempt_misconception_scan.py::_emit_adapter_shadow_records`):

    {"problem_id": "<uuid>", "adapter_records": ["<DerivativeShadowRecord JSON>", ...]}

이 CLI는 그 줄들을 모은 파일을 읽어, 독법을 `on`으로 켜도 되는지를 **사전 등록 기준**
(`docs/reviews/p3_56_derivative_signature_candidate_2026-10-18.md` §9.3)으로 판정하고 종료
코드로 말한다 — PASS 0 · FAIL 1 · 측정 불가 3.

    python -m whymath_backend.harness.attempt_scan_shadow_harvest shadow.jsonl
    python -m whymath_backend.harness.attempt_scan_shadow_harvest shadow.jsonl --json
    python -m whymath_backend.harness.attempt_scan_shadow_harvest shadow.jsonl --corpus-root bank

(`--corpus-root` 기본값은 저장소 `data/corpus` — 테스트는 임시 문항은행을 가리킨다.)

입력 계약(중요)
────────────────────────────────────────────────────────────────────────────
· 한 줄 = 로거 메시지 하나 **그대로**다. 수집 핸들러의 포매터는 `%(message)s`여야 한다 —
  uvicorn·`logging.basicConfig` 기본 포매터처럼 `INFO:whymath...:` 접두가 붙으면 그 줄은 JSON이
  아니므로 **1번째 줄에서 측정 불가**로 멈춘다(접두를 추측해 벗기지 않는다 — 형식이 틀린 입력을
  고쳐 읽으면 무엇을 읽었는지 말할 수 없다).
· 빈 줄과 `#`로 시작하는 줄은 건너뛴다(`wrong_form_shadow_harvest` 선례 — 수집 스크립트의 주석용).
· 같은 (문항 id, 어댑터 레코드 문자열)이 **바이트까지 같으면** 같은 사건의 이중 기록이다
  (레코드의 `observed_at`이 마이크로초 단위라 서로 다른 시도가 우연히 같을 수 없다). 중복은 한 번만
  세고, 건수를 `duplicate_records`로 보고하며 요약 상단에 경고한다 — 수집을 두 번 이어 붙인 파일이
  표본을 두 배로 부풀려 C1을 거짓 충족시키지 못하게 한다.

판정 기준(§9.3 — 수치는 **제안**이며 게이트 `G-p356-signature-activation`에서 Kiki가 확정한다)
────────────────────────────────────────────────────────────────────────────
  C1 표본       질문을 읽은 문항의 오답 시도 n ≥ 300. 미만은 FAIL이 아니라 측정 불가.
  C2 정답 오발화 정답 시도 중 `fired`가 1건이라도 있으면 FAIL(표본 크기와 무관 — 확인된 오발화는
                표본이 작다고 통과로 바뀌지 않는다). 확정 오발화가 0이어도 정답 여부를 모르는
                시도에서 발화가 있으면(`fired_unknown > 0`) 측정 불가 — 그것이 오발화인지 모른다.
                그 밖에 정답 시도가 100건 미만이면 측정 불가.
  C3 우연 초과   오답 발화율의 Wilson 95% 단측 하한 ≥ 5 × 기준선. 기준선은 문항별 우연 발화율
                (정답 ± 1..30 정수 답 60개 중 엔진이 `fired`를 내는 비율)을 오답 시도 수로 가중평균.
  C4 쏠림 없음   한 문항이 오답 발화의 30%를 넘으면 FAIL. 단 C1 표본(n ≥ 300) 미충족이면 측정 불가 —
                §9.3은 기준 간 순서를 정하지 않는다 — 이 순서는 도구의 결정(게이트에서 Kiki 확정).
  C0 데이터 정합 **기준선이 필요한 문항**(질문을 읽은 오답 시도가 1건 이상)이 문항은행에 없으면 측정
                불가(기준선을 잴 지문이 없다). 그 밖의 은행 미존재 문항은 정보로만 보고한다.

종합: FAIL이 하나라도 있으면 1 → 아니면 측정 불가가 하나라도 있으면 3 → 아니면 0. **모든 기준을
먼저 계산한 뒤** 판정한다 — 앞 기준에서 일찍 끝내면 나머지 값이 보고서에서 사라진다.

정직 스코프(중요)
────────────────────────────────────────────────────────────────────────────
· **기준선은 엔진을 직접 불러 잰다**(재구현 0). `answer_signature.scan_attempt_answer`를 그림자
  모드로 호출해 그 레코드의 `fired`를 센다 — 판정 로직을 이 파일에 다시 쓰면 엔진이 바뀔 때 기준선이
  조용히 어긋난다. 그림자 모드는 이 계산 동안에만 환경변수 + 설정 캐시 비우기로 켜고, 끝나면
  원복한다(전역 상태를 남기지 않는다 — `qa_pipeline._axis_coach_prose_leak` 선례).
· **기준선 후보 답마다 엔진이 실제로 일했는지 확인한다.** 레코드가 `rules_total > 0`이고
  `applicable is True`가 아니면 측정 불가다. 엔진은 규칙표 적재 실패를 삼키고 빈 결과를 돌려주므로
  (`answer_signature._read_derivative_channel`), 그것을 그대로 세면 60개 전부 미발화 → 기준선 0 →
  C3가 거짓 통과한다(작동한 비율 원칙).
· **문항 본문은 문항은행에서 읽는다.** 로그에는 문항 id만 있고 학생 답·지문은 없다(미성년 PII).
  이 CLI도 학생 답·지문을 출력하지 않는다 — 문항 id·건수·비율만 낸다.
· **모른다 ≠ 아니다.** `answer_is_correct is None`(질문을 못 읽음)은 오답으로 접지 않고 따로 센다.
· **빈 입력·깨진 입력은 통과가 아니다.** 파일 없음·형식 오류·미분 레코드 0건은 전부 측정 불가(3)다.
· DB·네트워크 0. 순수 파일 읽기 + 엔진 호출.

한계(정직)
────────────────────────────────────────────────────────────────────────────
· **기준선은 "정답 ± 30 정수 균등" 가정**이라 실제 계산 실수 분포(정답 근처 쏠림)와 다르다. 이
  판정은 정밀도를 직접 재지 않는다 — 발화가 우연 이상이라는 통계적 근거를 줄 뿐이다.
· **기준선 0/60을 참 0으로 취급한다.** 60개 표본의 0은 "우연 발화율이 작다"이지 "0이다"가 아니지만
  기준선에 신뢰경계를 씌우지 않는다(§9.3 문면이 점 기준선을 쓴다). 대신 C3는 발화율 하한이 0보다
  커야 통과한다 — 발화 0건이 기준선 0과 만나 공허하게 통과하지 않게.
· **레코드에 엔진·규칙표 버전이 없다.** 로그를 남긴 시점의 엔진과 이 CLI가 기준선을 재는 엔진이
  다르면(규칙 추가·수정) 그 차이를 탐지하지 못한다. 수확은 로그 수집 기간의 배포 버전과 같은
  커밋에서 돌려야 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from whymath_backend.config import get_settings
from whymath_backend.harness.wilson import wilson_lower_bound
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.symbolic_equivalence import to_sympy_source
from whymath_backend.l4.misconception import answer_signature as _signature
from whymath_backend.l4.misconception.answer_signature import DerivativeShadowRecord

logger = logging.getLogger("whymath.harness.attempt_scan_shadow_harvest")

__all__ = [
    "BASELINE_OFFSET_RANGE",
    "CHANCE_MULTIPLIER",
    "CONFIDENCE",
    "EXIT_FAIL",
    "EXIT_PASS",
    "EXIT_UNMEASURABLE",
    "MAX_SINGLE_PROBLEM_SHARE",
    "MIN_CORRECT_ATTEMPTS",
    "MIN_WRONG_ATTEMPTS",
    "BankProblem",
    "BaselineCache",
    "ChanceBaseline",
    "CriterionResult",
    "HarvestInputError",
    "HarvestReport",
    "ShadowLog",
    "Verdict",
    "compute_chance_baseline",
    "evaluate",
    "load_problem_bank",
    "load_shadow_log",
    "main",
    "run_harvest",
]

# ── 판정 기준(§9.3 사전 등록 · 제안값 — 게이트 G-p356-signature-activation에서 Kiki 확정) ──────

#: C1 — 질문을 읽은 문항의 오답 시도 최소 표본. 미만은 측정 불가(FAIL 아님).
MIN_WRONG_ATTEMPTS = 300
#: C2 — 정답 오발화 0건을 "확인됐다"고 말할 수 있는 정답 시도 최소 표본.
MIN_CORRECT_ATTEMPTS = 100
#: C3 — 발화율 하한이 기준선의 몇 배를 넘어야 하는가. 5배 = "발화 중 우연이 20% 이하".
CHANCE_MULTIPLIER = 5.0
#: C4 — 한 문항이 오답 발화에서 차지해도 되는 최대 비율(초과하면 FAIL). C1 표본 미충족이면 판정하지
#: 않고 측정 불가다(작은 표본의 쏠림 FAIL은 '기준 미달'로 오독된다 — 순서는 게이트에서 Kiki 확정).
MAX_SINGLE_PROBLEM_SHARE = 0.30
#: C3 기준선 — 정답 ± 1..이 값의 정수 답을 우연 답 후보로 쓴다(0 제외 → 60개).
BASELINE_OFFSET_RANGE = 30
#: C3 — Wilson 단측 신뢰수준.
CONFIDENCE = 0.95

EXIT_PASS = 0
EXIT_FAIL = 1
#: 잰 것이 없거나 잴 수 없으면 기준 미달이 아니라 측정 불가다(통과 위장 금지).
EXIT_UNMEASURABLE = 3

_CHANNEL = "derivative_signature"
_MODE_ENV = "WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_corpus_root() -> Path:
    return _repo_root() / "data" / "corpus"


class HarvestInputError(Exception):
    """입력(로그·문항은행·엔진)을 읽을 수 없다 — 판정이 아니라 측정 불가(exit 3)의 원인."""


class Verdict(StrEnum):
    """기준 하나 또는 종합의 판정 — 3상태."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNMEASURABLE = "UNMEASURABLE"


_VERDICT_LABEL = {
    Verdict.PASS: "통과",
    Verdict.FAIL: "실패",
    Verdict.UNMEASURABLE: "측정 불가",
}

_EXIT_BY_VERDICT = {
    Verdict.PASS: EXIT_PASS,
    Verdict.FAIL: EXIT_FAIL,
    Verdict.UNMEASURABLE: EXIT_UNMEASURABLE,
}


# ── 입력: 그림자 로그 ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ShadowLog:
    """로그 파일에서 읽은 미분 서명 관측 — `(문항 id, 레코드)` 목록 + 다른 채널·중복 건수."""

    lines: int
    records: tuple[tuple[str, DerivativeShadowRecord], ...]
    other_channel_records: int
    duplicate_records: int = 0


def _describe_validation_error(exc: ValidationError) -> str:
    """검증 실패를 **값 없이** 요약한다 — 위치·오류 종류만(입력 값이 출력에 새지 않게)."""
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        parts.append(f"{loc}:{err.get('type', '?')}")
    return ", ".join(parts)


def _line_error(line_no: int, exc: Exception, what: str) -> HarvestInputError:
    """줄 번호·예외 타입명이 든 측정 불가 사유를 만든다(지문·답 같은 필드값은 담지 않는다)."""
    detail = ""
    if isinstance(exc, ValidationError):
        detail = f" ({_describe_validation_error(exc)})"
    elif isinstance(exc, json.JSONDecodeError):
        detail = f" ({exc.msg} at pos {exc.pos})"
    return HarvestInputError(f"{line_no}번째 줄: {what} — {type(exc).__name__}{detail}")


def load_shadow_log(text: str) -> ShadowLog:
    """로그 JSONL 텍스트 → `ShadowLog`. 형식이 틀린 줄이 하나라도 있으면 `HarvestInputError`.

    빈 줄·`#` 줄만 건너뛴다. 한 줄은 `problem_id`(비어 있지 않은 문자열)와 `adapter_records`(문자열
    목록)를 가진 JSON 객체여야 한다. 레코드 문자열마다 `channel`을 보고, 미분 서명이면
    `DerivativeShadowRecord`로 **엄격 검증**한다(extra 금지 — 스키마 이탈을 조용히 흡수하지 않는다).
    다른 채널은 세기만 하고 버린다(이 CLI의 판정 대상이 아니다). 같은 (문항 id, 레코드 문자열)은
    한 번만 센다(모듈 docstring "입력 계약").
    """
    records: list[tuple[str, DerivativeShadowRecord]] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    other = 0
    lines = 0
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines += 1
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise _line_error(line_no, exc, "JSON이 아니다(수집 포매터가 %(message)s인가)") from exc
        if not isinstance(row, dict):
            raise HarvestInputError(f"{line_no}번째 줄: JSON 객체가 아니다 — {type(row).__name__}")
        problem_id = row.get("problem_id")
        adapter_records = row.get("adapter_records")
        if not isinstance(problem_id, str) or not problem_id.strip():
            raise HarvestInputError(f"{line_no}번째 줄: problem_id가 비었거나 문자열이 아니다")
        if not isinstance(adapter_records, list) or not all(
            isinstance(r, str) for r in adapter_records
        ):
            raise HarvestInputError(f"{line_no}번째 줄: adapter_records가 문자열 목록이 아니다")
        pid = problem_id.strip()
        for record_text in adapter_records:
            try:
                payload = json.loads(record_text)
            except json.JSONDecodeError as exc:
                raise _line_error(line_no, exc, "어댑터 레코드가 JSON이 아니다") from exc
            if not isinstance(payload, dict):
                raise HarvestInputError(
                    f"{line_no}번째 줄: 어댑터 레코드가 JSON 객체가 아니다 — "
                    f"{type(payload).__name__}"
                )
            if payload.get("channel") != _CHANNEL:
                other += 1
                continue
            try:
                record = DerivativeShadowRecord.model_validate_json(record_text)
            except ValidationError as exc:
                raise _line_error(line_no, exc, "미분 서명 레코드 스키마 불일치") from exc
            key = (pid, record_text)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            records.append((pid, record))
    return ShadowLog(
        lines=lines,
        records=tuple(records),
        other_channel_records=other,
        duplicate_records=duplicates,
    )


# ── 입력: 문항은행 ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BankProblem:
    """승인 문항 1건 — 기준선 계산에 필요한 필드만(지문은 엔진 호출에만 쓰고 출력하지 않는다)."""

    problem_id: str
    question_text: str
    answer: str


def load_problem_bank(corpus_root: Path, wanted: set[str]) -> dict[str, BankProblem]:
    """`corpus_root/problem_bank_*/problems.jsonl`의 **승인** 문항 중 `wanted` id만 읽는다.

    문항은행 파일이 하나도 없으면 `HarvestInputError`다 — 경로를 잘못 준 것을 "모든 문항이 은행에
    없다"로 보고하면 원인이 흐려진다. 같은 id가 서로 다른 지문·정답으로 두 번 나오면 어느 쪽으로
    기준선을 잴지 정할 수 없으므로 역시 측정 불가다.
    """
    paths = sorted(corpus_root.glob("problem_bank_*/problems.jsonl"))
    if not paths:
        raise HarvestInputError(f"문항은행 없음: {corpus_root}/problem_bank_*/problems.jsonl 0개")
    found: dict[str, BankProblem] = {}
    for path in paths:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HarvestInputError(
                    f"문항은행 {path.parent.name} {line_no}번째 줄: {type(exc).__name__}"
                ) from exc
            if not isinstance(row, dict) or row.get("review_status") != "approved":
                continue
            pid = str(row.get("problem_id", ""))
            if pid not in wanted:
                continue
            problem = BankProblem(
                problem_id=pid,
                question_text=str(row.get("question_text", "")),
                answer=str(row.get("answer", "")),
            )
            previous = found.get(pid)
            if previous is not None and previous != problem:
                raise HarvestInputError(f"문항은행에 같은 id가 다른 내용으로 두 번 있다: {pid}")
            found[pid] = problem
    return found


# ── C3 기준선: 엔진을 직접 불러 잰다 ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChanceBaseline:
    """문항 1개의 우연 발화율 — 정답 ± 1..30 정수 답 중 엔진이 `fired`를 낸 비율.

    `computable=False`면 정답을 파싱하지 못했거나 유한 실수가 아니어서 기준선을 정의할 수 없다 —
    그 문항의 오답 시도는 C3 부분집합에서 빠지고, 빠진 건수와 사유가 보고서에 남는다.
    """

    computable: bool
    fired: int = 0
    trials: int = 0
    reason: str = ""

    @property
    def rate(self) -> float | None:
        return self.fired / self.trials if self.computable and self.trials else None


#: 기준선 캐시 — 키는 (지문, 정답). 같은 실행 안에서 문항당 한 번만 엔진을 돌린다.
BaselineCache = dict[tuple[str, str], ChanceBaseline]


@contextmanager
def _shadow_mode() -> Iterator[None]:
    """이 블록 동안만 미분 서명 독법을 그림자 모드로 켠다 — 끝나면 환경·설정 캐시를 원복한다."""
    previous = os.environ.get(_MODE_ENV)
    os.environ[_MODE_ENV] = "shadow"
    get_settings.cache_clear()
    try:
        mode = get_settings().l4_derivative_signature_mode
        if mode != "shadow":
            # 설정 우선순위가 바뀌어 환경변수가 안 먹으면 기준선이 off 모드로 0이 된다 — 위장 금지.
            raise HarvestInputError(f"그림자 모드를 켜지 못했다(현재 모드 {mode})")
        yield
    finally:
        if previous is None:
            os.environ.pop(_MODE_ENV, None)
        else:
            os.environ[_MODE_ENV] = previous
        get_settings.cache_clear()


def _bank_answer_value(answer: str) -> tuple[Any | None, str]:
    """문항은행 정답을 SymPy 값으로 — 실패하면 `(None, 사유)`. 파싱 실패와 비실수를 구분한다."""
    try:
        value = safe_sympify(to_sympy_source(answer))
    except Exception as exc:  # noqa: BLE001 — 읽지 못한 정답은 '기준선 없음'으로 접고 원인을 남긴다
        logger.warning("문항은행 정답 파싱 실패: %s", type(exc).__name__)
        return None, f"정답 파싱 실패({type(exc).__name__})"
    if not getattr(value, "is_number", False):
        return None, "정답이 수가 아님(식·기호)"
    if value.is_real is not True or value.is_finite is not True:
        return None, "정답이 유한 실수가 아님"
    return value, ""


def compute_chance_baseline(problem: BankProblem) -> ChanceBaseline:
    """한 문항의 우연 발화율을 엔진으로 잰다. 호출자가 `_shadow_mode()` 안에서 불러야 한다.

    후보 답은 `str(정답 + k)`(k ∈ [-30, 30], k ≠ 0)이다. 후보마다 엔진이 **실제로 일했는지**를
    확인한다 — 그림자 레코드가 정확히 1건이고, 규칙이 적재됐고(`rules_total > 0`), 질문을
    읽었어야(`applicable is True`) 한다. 어기면 `HarvestInputError`(측정 불가): 일하지 않은 엔진의
    '미발화'를 세면 기준선이 0으로 내려가 C3가 거짓 통과한다.
    """
    value, reason = _bank_answer_value(problem.answer)
    if value is None:
        return ChanceBaseline(computable=False, reason=reason)
    fired = 0
    trials = 0
    for k in range(-BASELINE_OFFSET_RANGE, BASELINE_OFFSET_RANGE + 1):
        if k == 0:
            continue
        candidate = str(value + k)
        result = _signature.scan_attempt_answer(
            question_text=problem.question_text, student_answer=candidate
        )
        if len(result.shadow_records) != 1:
            raise HarvestInputError(
                f"기준선 계산 중 그림자 레코드가 {len(result.shadow_records)}건 — "
                f"문항 {problem.problem_id}"
            )
        record = DerivativeShadowRecord.model_validate_json(result.shadow_records[0])
        if record.rules_total <= 0:
            raise HarvestInputError(
                f"기준선 계산 불가 — 문항 {problem.problem_id}: 엔진 규칙 0건"
                "(규칙표 적재 실패 — 엔진 로그의 예외 타입명을 확인)"
            )
        if record.applicable is not True:
            raise HarvestInputError(
                f"기준선 계산 불가 — 문항 {problem.problem_id}: 엔진이 질문을 읽지 못함"
                "(로그 시점 엔진과 현재 엔진이 다를 수 있다)"
            )
        trials += 1
        fired += int(record.fired)
    return ChanceBaseline(computable=True, fired=fired, trials=trials)


# ── 집계 · 판정 ────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _ProblemTally:
    """문항 1개의 시도 분류 집계."""

    wrong: int = 0
    fired_wrong: int = 0
    correct: int = 0
    fired_correct: int = 0
    unknown: int = 0
    fired_unknown: int = 0


class CriterionResult(BaseModel):
    """기준 하나의 판정과 그 근거 수치."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: str
    verdict: Verdict
    detail: str
    values: dict[str, Any]


class ProblemRow(BaseModel):
    """문항별 집계 한 줄 — 문항 id와 건수·비율만(지문·학생 답 없음)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str
    in_bank: bool
    wrong: int
    fired_wrong: int
    correct: int
    fired_correct: int
    unknown: int
    fired_unknown: int
    baseline_rate: float | None
    baseline_note: str


class HarvestReport(BaseModel):
    """수확 결과 전체 — 지표 · 기준별 판정 · 종합 판정."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Verdict
    log_lines: int
    derivative_records: int
    duplicate_records: int
    other_channel_records: int
    applicable: int
    reach_rate: float | None
    wrong_attempts: int
    correct_attempts: int
    unknown_attempts: int
    fired_wrong: int
    fired_correct: int
    fired_unknown: int
    fire_rate: float | None
    unknown_bank_problems_info: tuple[str, ...]
    criteria: tuple[CriterionResult, ...]
    problems: tuple[ProblemRow, ...]


@dataclass(slots=True)
class _Tallies:
    per_problem: dict[str, _ProblemTally] = field(default_factory=dict)
    applicable: int = 0
    total: int = 0


def _classify(log: ShadowLog) -> _Tallies:
    """레코드를 오답·정답·모름으로 나눈다. `None`은 오답이 아니다(모른다 ≠ 아니다).

    모름으로 분류된 레코드의 발화도 따로 센다(`fired_unknown`) — 그것이 정답 위의 오발화인지 알 수
    없으므로 C2가 측정 불가로 다룬다. 정상 엔진에서는 질문을 못 읽으면 발화도 없지만, 레코드가 그
    불변식을 어기면 그것도 '모르는 발화'다.
    """
    tallies = _Tallies()
    for problem_id, record in log.records:
        tally = tallies.per_problem.setdefault(problem_id, _ProblemTally())
        tallies.total += 1
        if record.applicable:
            tallies.applicable += 1
        if record.applicable and record.answer_is_correct is False:
            tally.wrong += 1
            tally.fired_wrong += int(record.fired)
        elif record.applicable and record.answer_is_correct is True:
            tally.correct += 1
            tally.fired_correct += int(record.fired)
        else:
            tally.unknown += 1
            tally.fired_unknown += int(record.fired)
    return tallies


def _criterion_c0(missing: list[str]) -> CriterionResult:
    if missing:
        return CriterionResult(
            criterion="C0 데이터 정합",
            verdict=Verdict.UNMEASURABLE,
            detail=(
                f"오답 시도가 있는데 문항은행에 없는 문항 id {len(missing)}개 — "
                "지문이 없어 기준선을 잴 수 없다"
            ),
            values={"missing_problem_ids": sorted(missing)},
        )
    return CriterionResult(
        criterion="C0 데이터 정합",
        verdict=Verdict.PASS,
        detail="기준선이 필요한 모든 문항 id가 문항은행에 있다",
        values={"missing_problem_ids": []},
    )


def _criterion_c1(wrong: int) -> CriterionResult:
    verdict = Verdict.PASS if wrong >= MIN_WRONG_ATTEMPTS else Verdict.UNMEASURABLE
    return CriterionResult(
        criterion="C1 표본",
        verdict=verdict,
        detail=f"오답 시도 {wrong}건 (기준 ≥ {MIN_WRONG_ATTEMPTS})",
        values={"wrong_attempts": wrong, "min": MIN_WRONG_ATTEMPTS},
    )


def _criterion_c2(correct: int, fired_correct: int, fired_unknown: int) -> CriterionResult:
    # 확인된 오발화는 표본이 작아도 통과로 바뀌지 않는다 — 표본 검사보다 먼저 본다.
    if fired_correct > 0:
        verdict = Verdict.FAIL
        detail = f"정답 시도 {correct}건 중 오발화 {fired_correct}건"
    elif fired_unknown > 0:
        verdict = Verdict.UNMEASURABLE
        detail = (
            f"확정 오발화 0건이나 정답 여부를 모르는 시도의 발화 {fired_unknown}건 — "
            "그것이 오발화인지 알 수 없다"
        )
    elif correct < MIN_CORRECT_ATTEMPTS:
        verdict = Verdict.UNMEASURABLE
        detail = f"오발화 0건이나 정답 시도 {correct}건 (기준 ≥ {MIN_CORRECT_ATTEMPTS})"
    else:
        verdict = Verdict.PASS
        detail = f"정답 시도 {correct}건 중 오발화 0건"
    return CriterionResult(
        criterion="C2 정답 오발화",
        verdict=verdict,
        detail=detail,
        values={
            "correct_attempts": correct,
            "fired_correct": fired_correct,
            "fired_unknown": fired_unknown,
            "min": MIN_CORRECT_ATTEMPTS,
        },
    )


def _criterion_c3(
    per_problem: Mapping[str, _ProblemTally], baselines: Mapping[str, ChanceBaseline]
) -> CriterionResult:
    """기준선이 있는 문항의 오답 시도만으로 Wilson 하한 ≥ 5 × 가중 기준선을 본다."""
    subset_n = 0
    subset_fired = 0
    weighted_sum = 0.0
    excluded = 0
    for pid, tally in per_problem.items():
        if tally.wrong == 0:
            continue
        baseline = baselines.get(pid)
        rate = baseline.rate if baseline is not None else None
        if rate is None:
            excluded += tally.wrong
            continue
        subset_n += tally.wrong
        subset_fired += tally.fired_wrong
        weighted_sum += rate * tally.wrong
    values: dict[str, Any] = {
        "subset_wrong_attempts": subset_n,
        "subset_fired": subset_fired,
        "excluded_wrong_attempts": excluded,
        "multiplier": CHANCE_MULTIPLIER,
        "confidence": CONFIDENCE,
        "min": MIN_WRONG_ATTEMPTS,
    }
    if subset_n < MIN_WRONG_ATTEMPTS:
        return CriterionResult(
            criterion="C3 우연 초과",
            verdict=Verdict.UNMEASURABLE,
            detail=(
                f"기준선이 있는 문항의 오답 시도 {subset_n}건 (기준 ≥ {MIN_WRONG_ATTEMPTS}, "
                f"기준선 없어 제외 {excluded}건)"
            ),
            values=values,
        )
    weighted = weighted_sum / subset_n
    threshold = CHANCE_MULTIPLIER * weighted
    lower = wilson_lower_bound(subset_fired, subset_n, CONFIDENCE)
    values.update(
        {
            "weighted_baseline": weighted,
            "threshold": threshold,
            "wilson_lower": lower,
            "fire_rate": subset_fired / subset_n,
        }
    )
    # 기준선이 0이면 임계도 0이라 '발화 0'이 공허하게 통과한다 — 하한이 0보다 커야 우연 '초과'다.
    passed = lower > 0.0 and lower >= threshold
    return CriterionResult(
        criterion="C3 우연 초과",
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        detail=(
            f"발화 {subset_fired}/{subset_n} · Wilson 하한 {lower:.4f} vs "
            f"{CHANCE_MULTIPLIER:g}×기준선 {threshold:.4f} "
            f"(기준선 {weighted:.4f}, 제외 {excluded}건)"
        ),
        values=values,
    )


def _criterion_c4(per_problem: Mapping[str, _ProblemTally], wrong: int) -> CriterionResult:
    """쏠림 — **C1 표본(오답 n ≥ 300)이 충족될 때만** 판정한다. 미충족이면 측정 불가.

    발화 3건짜리 표본에서 "한 문항 100%"는 통계적으로 의미가 없는데 FAIL로 내면 "기준 미달"로
    오독된다. §9.3 문면은 기준 간 순서를 정하지 않으므로 이 순서는 이 도구의 결정이며 게이트에서
    Kiki가 확정한다. C2의 확정 오발화 FAIL 우선과는 다르다 — 오발화는 1건으로 확정되는 사건이지만
    쏠림은 분포의 성질이라 표본이 있어야 성립한다. 비중 수치는 측정 불가여도 보고한다.
    """
    total = sum(t.fired_wrong for t in per_problem.values())
    values: dict[str, Any] = {
        "total_fired": total,
        "max_share": None,
        "max_share_problem_id": None,
        "max": MAX_SINGLE_PROBLEM_SHARE,
        "wrong_attempts": wrong,
        "min_wrong_attempts": MIN_WRONG_ATTEMPTS,
    }
    share: float | None = None
    top_pid: str | None = None
    if total > 0:
        top_pid, top = max(per_problem.items(), key=lambda kv: (kv[1].fired_wrong, kv[0]))
        share = top.fired_wrong / total
        values.update({"max_share": share, "max_share_problem_id": top_pid})
    share_text = "—" if share is None else f"{share:.2%} (문항 {top_pid})"
    if wrong < MIN_WRONG_ATTEMPTS:
        return CriterionResult(
            criterion="C4 쏠림 없음",
            verdict=Verdict.UNMEASURABLE,
            detail=(
                f"오답 시도 {wrong}건 < {MIN_WRONG_ATTEMPTS} — 쏠림을 판정하지 않는다"
                f"(참고: 최대 비중 {share_text})"
            ),
            values=values,
        )
    if share is None:
        return CriterionResult(
            criterion="C4 쏠림 없음",
            verdict=Verdict.PASS,
            detail="오답 발화 0건 — 쏠림은 공허(우연 초과 여부는 C3가 판정한다)",
            values=values,
        )
    verdict = Verdict.FAIL if share > MAX_SINGLE_PROBLEM_SHARE else Verdict.PASS
    return CriterionResult(
        criterion="C4 쏠림 없음",
        verdict=verdict,
        detail=f"최대 비중 {share_text}, 기준 ≤ {MAX_SINGLE_PROBLEM_SHARE:.0%}",
        values=values,
    )


def _combine(criteria: tuple[CriterionResult, ...]) -> Verdict:
    """FAIL 하나라도 → FAIL, 아니면 측정 불가 하나라도 → 측정 불가, 아니면 PASS."""
    verdicts = {c.verdict for c in criteria}
    if Verdict.FAIL in verdicts:
        return Verdict.FAIL
    if Verdict.UNMEASURABLE in verdicts:
        return Verdict.UNMEASURABLE
    return Verdict.PASS


def evaluate(
    log: ShadowLog,
    bank: Mapping[str, BankProblem],
    baseline_fn: Callable[[BankProblem], ChanceBaseline],
) -> HarvestReport:
    """집계 → 기준선 → 기준 C0~C4를 **모두** 계산한 뒤 종합한다.

    `baseline_fn`은 문항 1개의 기준선을 낸다(실행에서는 캐시를 낀 엔진 호출). 기준선은 오답
    시도가 있는 문항에만 잰다 — 가중치가 오답 시도 수이므로 오답 0건 문항은 기여가 없다. 같은 이유로
    문항은행 존재는 그 문항들에만 요구하고(C0), 나머지 미존재 문항은 정보로만 보고한다.
    """
    tallies = _classify(log)
    missing = [pid for pid, t in tallies.per_problem.items() if t.wrong > 0 and pid not in bank]
    info_missing = [
        pid for pid, t in tallies.per_problem.items() if t.wrong == 0 and pid not in bank
    ]
    baselines: dict[str, ChanceBaseline] = {}
    for pid, tally in tallies.per_problem.items():
        if tally.wrong > 0 and pid in bank:
            baselines[pid] = baseline_fn(bank[pid])

    wrong = sum(t.wrong for t in tallies.per_problem.values())
    correct = sum(t.correct for t in tallies.per_problem.values())
    unknown = sum(t.unknown for t in tallies.per_problem.values())
    fired_wrong = sum(t.fired_wrong for t in tallies.per_problem.values())
    fired_correct = sum(t.fired_correct for t in tallies.per_problem.values())
    fired_unknown = sum(t.fired_unknown for t in tallies.per_problem.values())

    criteria = (
        _criterion_c0(missing),
        _criterion_c1(wrong),
        _criterion_c2(correct, fired_correct, fired_unknown),
        _criterion_c3(tallies.per_problem, baselines),
        _criterion_c4(tallies.per_problem, wrong),
    )
    rows = []
    for pid in sorted(tallies.per_problem):
        tally = tallies.per_problem[pid]
        baseline = baselines.get(pid)
        if pid not in bank:
            note = "문항은행에 없음"
        elif baseline is None:
            note = "오답 시도 0 — 기준선 불필요"
        elif not baseline.computable:
            note = baseline.reason
        else:
            note = f"{baseline.fired}/{baseline.trials}"
        rows.append(
            ProblemRow(
                problem_id=pid,
                in_bank=pid in bank,
                wrong=tally.wrong,
                fired_wrong=tally.fired_wrong,
                correct=tally.correct,
                fired_correct=tally.fired_correct,
                unknown=tally.unknown,
                fired_unknown=tally.fired_unknown,
                baseline_rate=baseline.rate if baseline is not None else None,
                baseline_note=note,
            )
        )
    return HarvestReport(
        verdict=_combine(criteria),
        log_lines=log.lines,
        derivative_records=tallies.total,
        duplicate_records=log.duplicate_records,
        other_channel_records=log.other_channel_records,
        applicable=tallies.applicable,
        reach_rate=tallies.applicable / tallies.total if tallies.total else None,
        wrong_attempts=wrong,
        correct_attempts=correct,
        unknown_attempts=unknown,
        fired_wrong=fired_wrong,
        fired_correct=fired_correct,
        fired_unknown=fired_unknown,
        fire_rate=fired_wrong / wrong if wrong else None,
        unknown_bank_problems_info=tuple(sorted(info_missing)),
        criteria=criteria,
        problems=tuple(rows),
    )


def run_harvest(
    log_path: Path,
    corpus_root: Path | None = None,
    *,
    baseline_cache: BaselineCache | None = None,
) -> HarvestReport:
    """파일 경로에서 판정까지 — 입력 결함은 `HarvestInputError`로 올린다(호출자가 exit 3).

    `baseline_cache`를 넘기면 여러 실행이 같은 기준선을 공유한다(테스트 재사용용). 넘기지 않으면
    이 실행 한정 캐시를 쓴다 — 어느 쪽이든 같은 (지문, 정답)에는 엔진을 한 번만 돌린다.
    """
    if not log_path.is_file():
        raise HarvestInputError(f"로그 파일 없음: {log_path}")
    try:
        text = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HarvestInputError(f"로그 파일을 읽지 못했다 — {type(exc).__name__}") from exc
    log = load_shadow_log(text)
    if not log.records:
        raise HarvestInputError(
            f"미분 서명 레코드 0건(유효 줄 {log.lines}·다른 채널 {log.other_channel_records}) — "
            "잴 것이 없다(통과로 읽지 않는다)"
        )
    wanted = {pid for pid, _ in log.records}
    bank = load_problem_bank(corpus_root or _default_corpus_root(), wanted)
    cache: BaselineCache = {} if baseline_cache is None else baseline_cache

    def _cached(problem: BankProblem) -> ChanceBaseline:
        key = (problem.question_text, problem.answer)
        hit = cache.get(key)
        if hit is None:
            hit = compute_chance_baseline(problem)
            cache[key] = hit
        return hit

    with _shadow_mode():
        return evaluate(log, bank, _cached)


# ── 출력 ───────────────────────────────────────────────────────────────────────────────────


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def render_summary(report: HarvestReport) -> str:
    """사람이 읽는 한국어 요약 — 문항 id·건수·비율만(지문·학생 답 없음)."""
    lines = ["미분 오답 서명 그림자 관측 — 활성화 판정 (P3-66 · §9.3 사전 등록 기준 · 수치는 제안)"]
    if report.duplicate_records:
        lines.append(
            f"⚠ 중복 레코드 {report.duplicate_records}건을 한 번만 셌다 — 같은 사건의 이중 기록"
            "(수집 파일을 이어 붙였는지 확인)"
        )
    if report.unknown_bank_problems_info:
        lines.append(
            f"ⓘ 문항은행에 없는 문항 {len(report.unknown_bank_problems_info)}개(오답 시도 0 — "
            "기준선 불필요, 판정에 영향 없음)"
        )
    lines += [
        f"· 로그 줄 {report.log_lines} · 미분 레코드 {report.derivative_records}"
        f" · 다른 채널 레코드 {report.other_channel_records}(무시)",
        f"· 도달률 — 앱 전체 텍스트 답안 시도(그림자 레코드가 남은 훑기) 대비 질문을 읽은 비율:"
        f" {report.applicable}/{report.derivative_records} = {_pct(report.reach_rate)}",
        f"· 오답 {report.wrong_attempts} · 정답 {report.correct_attempts}"
        f" · 모름(None·미적용) {report.unknown_attempts} — 모름은 오답으로 세지 않는다",
        f"· 오답 발화 {report.fired_wrong}/{report.wrong_attempts} = {_pct(report.fire_rate)}"
        f" · 정답 오발화 {report.fired_correct} · 모르는 시도의 발화 {report.fired_unknown}",
        "",
        "기준별 판정",
    ]
    for c in report.criteria:
        lines.append(f"  [{_VERDICT_LABEL[c.verdict]}] {c.criterion}: {c.detail}")
    lines += [
        "",
        "문항별 (문항 id · 오답 · 오답 발화 · 정답 · 정답 오발화 · 모름 · 모름 발화 · 기준선)",
    ]
    for row in report.problems:
        lines.append(
            f"  {row.problem_id} · {row.wrong} · {row.fired_wrong} · {row.correct}"
            f" · {row.fired_correct} · {row.unknown} · {row.fired_unknown}"
            f" · {_pct(row.baseline_rate)} ({row.baseline_note})"
        )
    return "\n".join(lines)


def _verdict_line(verdict: Verdict, exit_code: int) -> str:
    return f"VERDICT={verdict.value} ({_VERDICT_LABEL[verdict]}) EXIT={exit_code}"


def _emit_unmeasurable(reason: str, *, as_json: bool) -> int:
    """측정 불가를 출력하고 종료 코드 3을 돌려준다 — 사유는 지문·답 없이 원인만 담는다."""
    code = EXIT_UNMEASURABLE
    line = _verdict_line(Verdict.UNMEASURABLE, code)
    if as_json:
        payload = {"verdict": Verdict.UNMEASURABLE.value, "error": reason}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        sys.stderr.write(line + "\n")
    else:
        sys.stdout.write(f"측정 불가: {reason}\n\n{line}\n")
    return code


def main(argv: list[str] | None = None, *, baseline_cache: BaselineCache | None = None) -> int:
    """CLI 진입점 — 종료 코드가 판정이다(PASS 0 · FAIL 1 · 측정 불가 3).

    `--json`이면 stdout에는 JSON 객체 하나만 내고(기계가 파싱할 수 있게) 판정 줄은 stderr로 보낸다.
    `baseline_cache`는 테스트가 여러 실행에서 기준선을 공유하려고 넘기는 인자다(CLI는 쓰지 않는다).

    예기치 못한 예외(엔진 결함 등)도 측정 불가로 접는다 — 측정 도구가 터진 것을 FAIL(1)로 읽히게
    하면 "기준 미달"과 "못 쟀다"가 같은 숫자가 된다. 예외 타입명은 출력에, 트레이스백은 로그
    (`exc_info` — 핸들러가 없으면 logging의 최후 핸들러가 stderr로)에 남긴다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.attempt_scan_shadow_harvest",
        description="미분 오답 서명 그림자 관측 수확·활성화 판정 (PASS 0 · FAIL 1 · 측정 불가 3)",
    )
    parser.add_argument("log", type=Path, help="whymath.api.attempt_scan_shadow.record 로그 JSONL")
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="문항은행 루트(problem_bank_*/problems.jsonl). 기본: 저장소 data/corpus",
    )
    parser.add_argument("--json", action="store_true", help="stdout에 JSON 요약만 낸다")
    args = parser.parse_args(argv)

    try:
        report = run_harvest(args.log, args.corpus_root, baseline_cache=baseline_cache)
    except HarvestInputError as exc:
        return _emit_unmeasurable(str(exc), as_json=args.json)
    except Exception as exc:  # noqa: BLE001 — 측정 도구의 결함은 판정이 아니라 측정 불가다
        logger.error("수확 중 예기치 못한 예외: %s", type(exc).__name__, exc_info=True)
        return _emit_unmeasurable(f"예기치 못한 예외 — {type(exc).__name__}", as_json=args.json)

    code = _EXIT_BY_VERDICT[report.verdict]
    if args.json:
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
        sys.stderr.write(_verdict_line(report.verdict, code) + "\n")
    else:
        sys.stdout.write(render_summary(report) + "\n\n")
        sys.stdout.write(_verdict_line(report.verdict, code) + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover — CLI 진입
    raise SystemExit(main())
