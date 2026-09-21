"""서버측 답안 채점 shadow 리포트 — NLP-02(관측 전용 배치·요청 경로 무변경).

설계 정본: `docs/architecture/nlp_module_gap_review.md` §3 D2(Kiki 결정 2026-07-31 "측정
없는 도입 없음"). `student_answer`는 이미 요청 슬롯(`api/me.py::AttemptSubmitRequest`)이자
적재 컬럼(`db/models/activity.py::ProblemAttempt.student_answer`)이나 아무도 읽지 않는다 —
학습자 모델 전체(BKT·스킬 숙달 전파)가 검증되지 않은 클라이언트 `is_correct` 위에 서 있다.

이 모듈은 그 소비 0을 해소하되 **관측만** 한다:
  - `POST /v1/me/attempts`(`submit_attempt`)·`AttemptSubmitRequest`·`AttemptSubmitResponse`·
    두 mastery 전파 콜사이트(`record_problem_attempt_mastery`·`record_problem_attempt_skill_
    mastery`)는 **무변경**이다 — 이 모듈은 별도 배치 CLI(`main()`)로 분리되어 라이브 요청
    경로에 신규 SELECT·지연 0을 유지한다.
  - BKT/mastery 입력은 여전히 클라 보고 `is_correct`다(권위 이관 아님 — 이번 슬라이스는
    이중 회계 *관측*이며, "클라이언트를 믿어도 되는가"를 판단할 재료만 쌓는다).

conditions/answer_map 파생의 정확성 위험(핵심 — `derive_verify_inputs` 참조): `Problem`에는
`answer_map` 필드가 없다(이 태스크의 제약 — 신규 컬럼 0). 있는 재료는 `Problem.conditions_
parsed[*].formal`(자유서술 수식 문자열, 전 레포 소비자 0건 확인됨)과 단일 `Problem.answer`
뿐이다. 순진하게 `{"x": problem.answer}`를 무조건 답산맵으로 쓰는 것은 *안전하지 않다* —
조건의 실제 미지수가 `x`가 아니라 `y`·`t`·`n` 등이면, 대입 자체는 예외를 던지지 않고
`verify_answer`의 수치 샘플링 경로가 *엉뚱한 변수*에 값을 넣어 거짓 pass/fail을 만들 수
있다(조용한 오류 유입 — `verify_answer` 자체는 정직해도 호출자의 입력 조립이 틀리면 그
정직성이 무의미해진다). `derive_verify_inputs`가 이 위험의 유일한 방어선이다: 모든 조건의
`formal`이 파싱 가능하고 그 자유기호 합집합이 **정확히 하나**(단일 미지수)일 때만 파생하고,
아니면 `None`(비파생)으로 물러나 `verify_answer`를 아예 호출하지 않는다 — 다중 미지수 문항은
이 슬라이스의 의도적 스코프 밖이다.

  *NLP-09 정정(2026-09-10)*: 원 구현은 위 게이트를 자유기호가 정확히 `{"x"}`일 때로 적었다.
  이름을 못 박은 것은 위 위험의 보수적 *대리 지표*였는데, 실측이 그 대리가 과했음을 보였다 —
  코퍼스 파생 실패 7,048건 중 진짜 다중 미지수는 **0건**이고 전량 단일 미지수 `y`였다
  (`4*1/5 = y` 등). 게다가 미적분 은행은 `Integral(4*x**2+x-2,(x,0,2)) + 8 = y`처럼 `x`가
  이미 적분 변수라, 코퍼스를 `x`로 "교정"하는 쪽이 오히려 충돌을 만든다. 그래서 판정 기준을
  이름에서 **개수**로 옮겼다: 미지수가 하나뿐이면 오인할 대상 자체가 없고, 그 이름은 조건식
  에서 읽어 오면 된다. 코퍼스 경로는 여기에 더해 **답산맵 키 == 조건식의 그 자유기호**까지
  요구하므로 계약이 오히려 강해졌다(이전에는 코퍼스 경로가 자유기호를 아예 보지 않았다).

**채점 대상은 항상 학생 제출값이다**: `derive_verify_inputs`가 반환하는 `answer_map`은
`Problem.answer`(문항 정답 본문)로 채워지지만, 이는 파생 가능성(자유기호 게이트)을 확정하는
*틀*일 뿐이다. 실제 shadow 채점(`grade_attempt`)은 그 틀의 변수명에 **학생이 실제로 제출한
`student_answer`**를 대입해 `verify_answer`를 호출한다 — `Problem.answer`를 그대로 검산하면
"문항 자체의 자기정합성"만 확인할 뿐 학생 채점이 되지 않는다.

이중 회계(acceptance④): "검산 불가"(conditions/answer_map을 못 만들었거나 학생이 답을 아예
제출하지 않음)와 "검산은 했으나 unverifiable"(`verify_answer`가 3상태 중 unverifiable을
정직하게 반환)은 *서로 다른, 겹치지 않는* 버킷이다 — 전자는 `not_derivable_count`, 후자는
`verdict_counts["unverifiable"]`. 섞으면 "우리가 입력을 못 만들었다"와 "검증기가 모른다고
답했다"가 뒤섞여 실효 커버리지 판단이 왜곡된다(§4 D2 acceptance②·④ 정합).

교수학 금기(acceptance②): `unverifiable`은 오답으로 강등하지 않는다 — `client_grade_mismatch`
집계는 verdict가 `pass`/`fail`일 때만 클라 보고와 대조한다.

채점 가능성 상한(REC-05·`ai_recommendation_module_gap_review_2.md` §2 G1): 위 shadow 채점의
파생 게이트(`derive_verify_inputs`)는 코퍼스 2,638문항 중 **0건**만 통과한다(조건 보유 30건
전부 `formal` 결측) — 이 경로만으로는 attempt가 아무리 쌓여도 채점 가능성 관측이 영구히 0건
이다. `classify_gradability`/`build_gradability_ceiling_report`는 **attempt 없이 코퍼스만으로**
채점 가능성의 실제 상한(선택형 정확일치·수치 단답 후보·조건 기반 파생 3버킷)을 측정하는
별도 정적 리포트다 — `derive_verify_inputs`를 C버킷 판정에 그대로 재사용하되(중복 로직 0),
attempt 유무와 무관하게 코퍼스 전량을 스캔한다.

  *수치 현행화(REC-09 회수 시점 2026-08-11)*: 원 구현(REC-05·2026-08-09)은 위 자리를
  **2,647**문항으로 적었다. 그 사이 main이 전진해 `QUAL-02`(PR #777)가 실중복 9레코드를
  은퇴시켰다(2,647 − 9 = **2,638** · 근거 `docs/data/problem_duplicate_disposition_2026-08.md`).
  회수 세션 실측(`data/corpus/problem_bank_*/problems.jsonl` 7종 합계 2,638 · 버킷
  A 1,612 / B 1,026 / C 0 / unclassified 0)으로 갱신했다. **구조적 결론은 불변**이다 —
  C버킷 0건과 그 원인(조건 보유 30건 전부 `formal` 결측)은 코퍼스가 줄기 전후로 동일하다.

NLP-05 추가(2026-08-14): `derive_verify_inputs`가 `Problem.conditions_parsed`뿐 아니라
코퍼스 `verify.{conditions,answer_map}`을 공급원으로 삼는다. 코퍼스 2,638건 중
verify 블록(conditions+answer_map)을 보유한 것은 2,124건이며, 이 중 단일 미지수 `x`로
파생 가능한 것도 2,124건(실측). `classify_gradability` 우선순위를 A→C→B로 조정해
symbolic 파생 가능한 문항이 '수치 단답 후보'보다 정확한 경로로 계상되게 했다. 그 결과
코퍼스 전체 기준 **A 1,612 / C 872 / B 154 / unclassified 0**이며, C버킷이 0에서
올라감으로써 `verify_answer` 실제 호출의 입력 공급이 확인된다.

구조적 0 원인 구분(acceptance②): `ShadowGradingReport.verifiable_zero_reason`이 "표본
없음(attempt 0행)"과 "파생 가능 문항 0(코퍼스 formal 결측)"을 구분한다 — 이전에는 둘 다
`mismatch_rate=None`으로 같은 값이었다(변별력 없음).

CI 배선(acceptance⑤): 이 모듈의 CLI는 독립 CI job으로 배선돼 있지 않다(게이트가 아닌 관측
리포트라 실익 없음 — `ops/recommendation_reach_report.py`와 동일 패턴). `tests/backend/
harness/test_attempt_grading_shadow_report.py`가 pytest로 이 모듈의 순수 로직·CLI 분기를
검증하고, 그 pytest 경로 자체의 실재성은 `tests/infra/test_test_suite_wiring.py`가 결함주입
으로 상시 보증한다("저장소에 존재함"과 "돌아감"의 간극은 이 두 겹으로 이미 분리돼 있다).

사용:
    python -m whymath_backend.harness.attempt_grading_shadow_report
    python -m whymath_backend.harness.attempt_grading_shadow_report --json out/shadow.json
    python -m whymath_backend.harness.attempt_grading_shadow_report --mode ceiling
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast, get_args

import sympy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt as ProblemAttemptORM
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.l3.verify_answer import AnswerVerdict, verify_answer
from whymath_backend.schema.enums import AnswerFormat, QuestionFormat
from whymath_backend.schema.problem import Problem

__all__ = [
    "AttemptRecord",
    "GradabilityBucket",
    "GradabilityCeilingReport",
    "ShadowGradingReport",
    "build_gradability_ceiling_report",
    "build_report",
    "classify_gradability",
    "derive_verify_inputs",
    "fetch_all_problems",
    "fetch_attempt_records",
    "grade_attempt",
    "gradability_report_to_json",
    "main",
    "render_gradability_ceiling_report",
    "render_report",
    "report_to_json",
]

# 침묵실패 금지(CLAUDE.md) — 파생 실패는 보수적 None 반환이 정상 동작이라 raise하지 않지만,
# 예외 *타입명*은 debug로 남겨 계통 장애(예: formal 파싱 실패가 특정 예외로 폭증)를 관측 가능하게
# 한다(verify_answer.py의 동일 관례 — `logger.debug("... 보수 회피: %s", type(exc).__name__)`).
logger = logging.getLogger("whymath.harness.attempt_grading_shadow_report")

# 이 슬라이스가 지원하는 미지수 **개수** — 이름이 아니다(NLP-09).
#
# 원래는 `_SUPPORTED_UNKNOWN = "x"`였다. 이름을 못 박은 것은 "엉뚱한 변수에 학생 답을 대입"
# 하는 사고를 막으려는 보수적 대리 지표였는데, 실측이 그 대리가 과했음을 보여 줬다 —
# 파생 실패 7,048건이 전량 단일 미지수이고 이름만 `y`였다(진짜 다중 미지수 0건).
# 지켜야 할 불변식은 이름이 아니라 **미지수가 하나뿐일 것**이다. 하나뿐이면 오인할 대상 자체가
# 없고, 그 이름은 조건식에서 읽어 오면 된다.
_SUPPORTED_UNKNOWN_COUNT = 1

# NLP-05 — 파생 실패 원인(acceptance⑤). `derive_verify_inputs`가 None을 반환할 때의 사유.
_NotDerivableReason = Literal[
    "no_problem",
    "no_student_answer",
    "no_verify_input",
    "parse_error",
    "multi_symbol",
]

# NLP-05 — ceiling 리포트 unclassified 원인(acceptance⑤).
_UnclassifiedReason = Literal[
    "no_verify_block",
    "parse_error",
    "multi_symbol",
]


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 verify 블록 로더(NLP-05)
# ──────────────────────────────────────────────────────────────────────────
def _repo_root() -> Path:
    """`src/backend/whymath_backend/harness/attempt_grading_shadow_report.py`에서 repo root 반환."""
    return Path(__file__).resolve().parents[4]


@functools.lru_cache(maxsize=1)
def _load_corpus_verify_blocks() -> dict[str, tuple[list[str], dict[str, str]]]:
    """`data/corpus/problem_bank_*/problems.jsonl`에서 `verify.{conditions,answer_map}`만 추출.

    반환: slug에서 (conditions 리스트, answer_map)로 매핑. `verify.conditions`는 단일 문자열이므로
    `[conditions]` 형태로 반환해 `verify_answer`의 `Sequence[str]` 인터페이스와 맞춘다.
    slug가 없는 레코드는 건너뛴다 -- DB `Problem.slug`가 nullable이라 역조회 불가.
    """
    blocks: dict[str, tuple[list[str], dict[str, str]]] = {}
    corpus_root = _repo_root() / "data" / "corpus"
    for path in sorted(corpus_root.glob("problem_bank_*/problems.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:  # pragma: no cover — 파일 누락 시 정직히 skip(테스트 환경 변이)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            slug = record.get("slug")
            if not slug:
                continue
            verify = record.get("verify") or {}
            conditions = verify.get("conditions")
            answer_map = verify.get("answer_map")
            if (
                not isinstance(conditions, str)
                or not conditions.strip()
                or not isinstance(answer_map, dict)
                or not answer_map
            ):
                continue
            blocks[str(slug)] = (
                [conditions],
                {str(k): str(v) for k, v in answer_map.items()},
            )
    return blocks


def _free_symbol_names(parsed: object) -> set[str] | None:
    """파싱된 식의 자유기호 이름 집합. 자유기호를 물을 수 없는 값이면 `None`.

    `sympy.sympify("1 == 1")`처럼 파싱 결과가 파이썬 `bool`이면 `free_symbols` 자체가 없다.
    그 경우 "자유기호 0개"가 아니라 **모른다**로 돌려준다 — 모른다를 아니다로 접으면
    판정 불가 상태가 확정 신호로 둔갑한다(CLAUDE.md "모른다 ≠ 아니다").
    실측상 현재 코퍼스 13,520블록에는 이 경로에 걸리는 건이 0이지만, 미지수 계약은
    이 모듈의 유일한 방어선이므로 모르는 입력에서는 통과가 아니라 후퇴한다.
    """
    symbols = getattr(parsed, "free_symbols", None)
    if symbols is None:
        return None
    return {str(s) for s in symbols}


def _parse_for_derivation(condition: str) -> sympy.Basic | None:
    """코퍼스 conditions 문자열을 verify_answer 수준의 관용도로 파싱한다(실패 시 `None`).

    `verify_answer._parse_condition`은 `=`/`==`/`Eq` 등을 모두 등식 잔차로 정규화하지만,
    `sympy.sympify` 단독으로는 `=`를 파이썬 대입문으로 보아 예외를 던진다. derivation 게이트는
    실제 검산기와 동일한 관용도를 허용해야 하므로, 등호 정규화 후 sympify를 시도한다.

    NLP-09: 반환형이 `bool`에서 **파싱된 식**으로 바뀌었다. 미지수 계약(단일 자유기호)을
    판정하려면 파싱 성공 여부가 아니라 그 식의 `free_symbols`가 필요하기 때문이다 —
    "파싱은 됐다"만 알고 자유기호를 안 보면 답산맵 키와 조건의 미지수가 어긋나도 통과한다.
    """
    normalized = condition.strip()
    if not normalized:
        return None
    # `=` 단독을 `==`로 정규화 -- `<=`, `>=`, `!=`, `==`는 건드리지 않는다.
    if (
        "=" in normalized
        and "==" not in normalized
        and "<=" not in normalized
        and ">=" not in normalized
        and "!=" not in normalized
    ):
        normalized = normalized.replace("=", "==", 1)
    try:
        return sympy.sympify(normalized, evaluate=False)
    except Exception:  # noqa: BLE001
        return None


def _derive_from_corpus(
    problem: Problem,
) -> tuple[list[str], dict[str, str]] | _UnclassifiedReason:
    """`Problem.slug`로 코퍼스 verify 블록을 역조회해 **단일 미지수** 파생 재료를 만든다.

    실패 시 `UnclassifiedReason` 문자열을 반환해 ceiling/shadow 리포트의 사유 계수를 채운다.

    NLP-09 — 미지수 이름 `x` 하드코딩을 걷어냈다. 이전 게이트는 `answer_map` 키가 정확히
    `{"x"}`가 아니면 전부 `multi_symbol`로 물렸는데, 실측 결과 그 7,048건은 **하나도**
    다중 미지수가 아니었다: 전량 단일 미지수이며 이름이 `y`일 뿐이었다(예: `4*1/5 = y`).
    코퍼스 저작이 틀린 것도 아니다 — 미적분 은행은 `Integral(4*x**2+x-2,(x,0,2)) + 8 = y`
    처럼 `x`가 이미 적분 변수로 쓰이므로, `y`를 `x`로 바꾸는 "교정"은 오히려 충돌을 만든다.
    즉 결함은 데이터가 아니라 파생기 쪽이었다.

    다만 이름만 넓히면 위험하다. 모듈 docstring이 경고하는 진짜 사고는 "엉뚱한 변수에 값을
    넣는 것"이고, 이름 자체는 그 위험의 대리 지표였을 뿐이다. 그래서 실제 불변식으로 바꾼다 —
    **조건식의 자유기호가 정확히 하나이고 그것이 answer_map의 유일한 키와 같을 것.**
    이는 기존보다 *강한* 계약이다: 예전에는 코퍼스 경로가 자유기호를 아예 보지 않아
    `answer_map {"x": ...}` + `conditions "y + 1 = 0"` 같은 어긋난 짝도 통과했다.

    판정 순서도 바꿨다(파싱 → 미지수 계약). 자유기호를 보려면 먼저 파싱돼야 하므로,
    "파싱도 안 되는 식의 미지수"를 먼저 판정하던 이전 순서는 성립하지 않는다.
    """
    if not problem.slug:
        return "no_verify_block"
    blocks = _load_corpus_verify_blocks()
    item = blocks.get(problem.slug)
    if item is None:
        return "no_verify_block"
    conditions, answer_map = item
    if not conditions or not conditions[0].strip():
        return "no_verify_block"
    parsed = _parse_for_derivation(conditions[0])
    if parsed is None:
        logger.debug("derive_verify_inputs corpus 비파생(conditions 파싱 실패)")
        return "parse_error"
    free_symbols = _free_symbol_names(parsed)
    if (
        free_symbols is None
        or len(free_symbols) != _SUPPORTED_UNKNOWN_COUNT
        or free_symbols != set(answer_map)
    ):
        return "multi_symbol"
    return conditions, answer_map


# ──────────────────────────────────────────────────────────────────────────
# 파생 — conditions/answer_map(모듈 docstring의 핵심 위험 지점)
# ──────────────────────────────────────────────────────────────────────────
def _derive_from_conditions_parsed(
    problem: Problem,
) -> tuple[list[str], dict[str, str]] | _NotDerivableReason:
    """DB `Problem.conditions_parsed[*].formal` 경로 — REC-05 원 로직.

    실패 시 `NotDerivableReason` 문자열을 반환한다. `conditions_parsed`가 비거나
    `answer`가 없으면 "no_verify_input" — 코퍼스 fallback을 시도할 수 있음을 의미.
    """
    if not problem.conditions_parsed:
        return "no_verify_input"
    if not problem.answer or not problem.answer.strip():
        return "no_verify_input"

    formals: list[str] = []
    free_symbols: set[str] = set()
    for condition in problem.conditions_parsed:
        formal = condition.formal
        if not formal or not formal.strip():
            return "no_verify_input"
        try:
            parsed = sympy.sympify(formal, evaluate=False)
        except Exception as exc:  # noqa: BLE001 — 파싱 불가는 보수적 비파생(pass 위장 금지)
            logger.debug("derive_verify_inputs 비파생(formal 파싱 실패): %s", type(exc).__name__)
            return "parse_error"
        names = _free_symbol_names(parsed)
        if names is None:
            return "parse_error"
        free_symbols |= names
        formals.append(formal)

    # NLP-09 — 미지수 **이름**이 아니라 **개수**로 판정한다. DB 경로에는 answer_map이 없고
    # 이름 없는 `problem.answer` 하나뿐이라, 답산맵 키는 조건식에서 읽어 와야 한다. 예전처럼
    # `{"x": answer}`를 무조건 만들면 조건이 `y`를 쓸 때 학생 답이 `y`가 아닌 `x`에 들어가
    # `y`가 미결 자유기호로 남는다 — 모듈 docstring이 경고하는 "엉뚱한 변수" 그 자체다.
    # 자유기호가 정확히 하나면 오인할 대상이 없으므로, 그 이름을 그대로 키로 쓴다.
    if len(free_symbols) != _SUPPORTED_UNKNOWN_COUNT:
        return "multi_symbol"
    return formals, {next(iter(free_symbols)): problem.answer}


def _derive_verify_inputs_with_reason(
    problem: Problem,
) -> tuple[tuple[list[str], dict[str, str]], None] | tuple[None, _NotDerivableReason]:
    """파생 재료 + 실패 사유를 함께 반환하는 내부 헬퍼(NLP-05 acceptance⑤).

    `_derive_from_corpus`의 `no_verify_block`은 shadow 리포트 사유 체계에서
    `no_verify_input`으로 통합한다 — 둘 다 "검산 재료가 없음"을 의미하며,
    세분화된 `no_verify_block`은 ceiling 리포트 전용이다.
    """
    parsed = _derive_from_conditions_parsed(problem)
    if isinstance(parsed, tuple):
        return parsed, None
    if parsed == "no_verify_input":
        corpus = _derive_from_corpus(problem)
        if isinstance(corpus, tuple):
            return corpus, None
        if corpus == "no_verify_block":
            return None, "no_verify_input"
        return None, cast(_NotDerivableReason, corpus)
    return None, parsed


def derive_verify_inputs(problem: Problem) -> tuple[list[str], dict[str, str]] | None:
    """`Problem.conditions_parsed[*].formal` + `Problem.answer` → verify_answer 입력 파생.

    **단일 미지수** 문항만 지원한다 — 이름은 묻지 않는다(NLP-09 · 모듈 docstring 위험 설명).
    다음 중 하나라도 해당하면 `None`(비파생) — **`verify_answer`를 호출하지 않는다**
    (false mismatch 근원 차단):
      - 조건이 하나도 없음(`conditions_parsed`가 빈 목록)
      - `Problem.answer`가 없거나 공백만
      - 어느 조건의 `formal`이 없거나 공백만
      - 어느 조건의 `formal`이 SymPy로 파싱 불가(구문 오류 등 — 보수적 회피)
      - 조건들의 자유기호 합집합의 크기가 1이 아님(미지수가 없거나 둘 이상인 경우 —
        이 게이트가 "학생 답을 엉뚱한 변수에 대입"하는 오류를 막는 유일한 방어선이다.
        미지수가 하나면 대입할 자리가 하나뿐이라 오인 자체가 성립하지 않으므로, 이름이
        `x`든 `y`든 `t`든 안전하다)

    NLP-05 추가: `conditions_parsed`로 파생 불가하면 `Problem.slug`로 코퍼스
    `verify.{conditions,answer_map}`을 역조회해 재시도한다. 코퍼스 verify 블록은
    `data/corpus/problem_bank_*/problems.jsonl`의 2,124건(전체 2,638건 중)에 존재하며,
    전부 단일 미지수 `x`다(실측). 이 경로로 `derive_verify_inputs`가 0에서 벗어나
    `verify_answer`가 실제 호출된다.

    반환은 `(conditions, answer_map)`이며 `answer_map`은 `{조건식의 유일한 미지수:
    problem.answer}` — 키 이름이 `"x"`로 고정되지 않는다(NLP-09). 이 값은 "파생 가능성이
    확정됐다"는 *틀*일 뿐, 실제 shadow 채점은 `grade_attempt`가 이 틀의 키에 학생 제출값을
    대입해서 이뤄진다(모듈 docstring "채점 대상은 항상 학생 제출값이다"). 코퍼스 경로에서는
    코퍼스가 적어 둔 `answer_map`을 그대로 쓰되, 그 키가 조건식의 자유기호와 같을 때만이다.
    """
    result, _reason = _derive_verify_inputs_with_reason(problem)
    return result


def _grade_attempt_with_reason(
    problem: Problem, student_answer: str | None
) -> tuple[AnswerVerdict | None, _NotDerivableReason | None]:
    """`grade_attempt`의 사유 반환 버전(NLP-05 acceptance⑤)."""
    if student_answer is None or not student_answer.strip():
        return None, "no_student_answer"
    derived, reason = _derive_verify_inputs_with_reason(problem)
    if derived is None:
        return None, reason
    conditions, canonical_answer_map = derived
    student_map = dict.fromkeys(canonical_answer_map, student_answer)
    return verify_answer(conditions, student_map), None


def grade_attempt(problem: Problem, student_answer: str | None) -> AnswerVerdict | None:
    """(문항, 학생 제출 답안) → shadow 채점 verdict. `None`이면 not_derivable.

    `student_answer`가 없거나(None·공백) `derive_verify_inputs`가 비파생을 돌리면 `None`
    (검산 자체를 시도하지 않음 — acceptance①의 "student_answer가 있고 문항이 검산 가능하면"
    두 전제를 모두 만족할 때만 `verify_answer`를 호출한다).

    실제 대입값은 항상 `student_answer`다 — `derive_verify_inputs`가 돌린 `answer_map`은
    미지수 이름(`x`)만 취하고 값은 버린다(그 값은 `Problem.answer`이지 채점 대상이 아니다).
    """
    verdict, _reason = _grade_attempt_with_reason(problem, student_answer)
    return verdict


# ──────────────────────────────────────────────────────────────────────────
# 조회 — attempt+problem 조인(얇은 I/O, 집계 로직 0 — 순수 코어는 build_report)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class AttemptRecord:
    """DB에서 읽은 attempt 1건의 최소 투영 — `build_report`(순수 집계)의 유일한 입력.

    `problem`이 `None`이면 `problem_id`가 NULL이거나 FK가 고아(조인 실패)인 경우다 —
    `build_report`는 이를 예외 없이 `not_derivable`로 집계한다(관측 정직성 — 조용히 skip해
    분모를 왜곡하지 않는다).
    """

    attempt_id: uuid.UUID
    student_answer: str | None
    client_is_correct: bool | None
    problem: Problem | None


async def fetch_attempt_records(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[AttemptRecord]:
    """`problem_attempt` ⋈ `problem` 조회 → `AttemptRecord` 리스트(각 `to_schema()` 변환).

    `user_id`(선택)로 한 사용자로 스코핑할 수 있다(운영 디버그·테스트 격리 — 생략하면 전량).
    `problem_id`가 NULL이거나 참조 문제가 삭제된 attempt는 outer join으로 `problem=None`을
    받아 집계 단계(`build_report`)에서 `not_derivable`로 처리한다(예외로 튕기지 않는다).
    """
    stmt = select(ProblemAttemptORM, ProblemORM).outerjoin(
        ProblemORM, ProblemAttemptORM.problem_id == ProblemORM.problem_id
    )
    if user_id is not None:
        stmt = stmt.where(ProblemAttemptORM.user_id == user_id)
    stmt = stmt.order_by(ProblemAttemptORM.attempt_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    records: list[AttemptRecord] = []
    for attempt_row, problem_row in rows:
        records.append(
            AttemptRecord(
                attempt_id=attempt_row.attempt_id,
                student_answer=attempt_row.student_answer,
                client_is_correct=attempt_row.is_correct,
                problem=problem_row.to_schema() if problem_row is not None else None,
            )
        )
    return records


async def fetch_all_problems(session: AsyncSession) -> list[Problem]:
    """`problem` 테이블 전량 스캔(REC-05 채점 가능성 상한 리포트 전용 — attempt 무관).

    페이지네이션 없이 `.all()`로 전량 로드한다(이 저장소의 확립된 관례 —
    `fetch_attempt_records`·`api/gating.py:_fetch_candidates`와 동형, 코퍼스 규모(수천 건)에
    적합). 각 row는 `to_schema()`로 Pydantic 스키마 변환한다 — ORM 컬럼을 직접 select하면
    `conditions_parsed`가 raw `list[dict]`로 나와 `derive_verify_inputs`가 기대하는
    `Condition` 객체 속성 접근(`condition.formal`)이 깨진다.
    """
    stmt = select(ProblemORM)
    rows = (await session.execute(stmt)).scalars().all()
    return [row.to_schema() for row in rows]


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 이중 회계 리포트(순수 코어 — DB·LLM·HTTP 0)
# ──────────────────────────────────────────────────────────────────────────
_VerdictState = Literal["pass", "fail", "unverifiable"]


@dataclass(slots=True, frozen=True)
class ShadowGradingReport:
    """shadow 채점 집계 결과 전량(불변) — `l4.content_supply.SupplyTally` 이중 회계 관례 답습.

    `mismatch_rate`/`unverifiable_rate`는 `verifiable_count == 0`이면 `None`이다(분모 없는
    0 금지 — "미상"을 0%로 위장하지 않는다). `client_grade_mismatch_count`는 `verifiable_count`
    행(검산이 실제로 이뤄진 행)만을 모집단으로 하고, 그중에서도 `unverifiable` verdict는
    대조 대상에서 제외한다(acceptance② — 판정 불가를 오답 신호로 쓰지 않는다).

    NLP-05 — `not_derivable_reason_counts`가 파생 불가의 세부 원인을 계수한다:
    `no_problem`(문항 조인 실패), `no_student_answer`, `no_verify_input`,
    `parse_error`, `multi_symbol`. 이 합은 `not_derivable_count`와 같다.
    """

    total_attempts: int
    not_derivable_count: int
    verifiable_count: int  # == total_attempts - not_derivable_count
    # {"pass": n, "fail": n, "unverifiable": n}
    verdict_counts: dict[str, int] = field(default_factory=dict)
    client_grade_mismatch_count: int = 0
    # NLP-05 — 파생 불가 세부 사유(acceptance⑤).
    not_derivable_reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def mismatch_rate(self) -> float | None:
        """불일치율(검산 가능 표본 대비). 표본 0이면 `None`(분모 없는 0 금지)."""
        if self.verifiable_count == 0:
            return None
        return self.client_grade_mismatch_count / self.verifiable_count

    @property
    def unverifiable_rate(self) -> float | None:
        """unverifiable 비율 — 이 기능의 *실효 커버리지*(§4 D2). 표본 0이면 `None`."""
        if self.verifiable_count == 0:
            return None
        return self.verdict_counts.get("unverifiable", 0) / self.verifiable_count

    @property
    def verifiable_zero_reason(self) -> Literal["no_sample", "not_derivable"] | None:
        """`verifiable_count == 0`의 원인 구분(REC-05 acceptance②).

        이전에는 "표본 자체가 없음"(`total_attempts == 0`)과 "표본은 있으나 전량 파생
        실패"(`not_derivable_count == total_attempts > 0`)가 둘 다 `mismatch_rate=None`으로
        같은 값이었다 — 변별력 없는 검증 스텝(CLAUDE.md 2026-07-17 등재)이었다. `verifiable_
        count > 0`이면 원인 구분이 필요 없으므로 `None`.
        """
        if self.verifiable_count > 0:
            return None
        return "no_sample" if self.total_attempts == 0 else "not_derivable"

    def to_json(self) -> dict[str, Any]:
        return report_to_json(self)


def build_report(records: list[AttemptRecord]) -> ShadowGradingReport:
    """attempt 레코드 목록 → `ShadowGradingReport`(순수·부작용 0).

    각 레코드에 대해:
      1. `problem`이 없으면 `not_derivable`(FK 고아·문제 삭제) — 사유 `no_problem`.
      2. `student_answer`가 없으면 `not_derivable` — 사유 `no_student_answer`.
      3. 파생 불가면 `not_derivable` — 사유 `no_verify_input`/`parse_error`/`multi_symbol`.
      4. 그 외 verdict(`pass`/`fail`/`unverifiable`)를 `verdict_counts`에 누적하고,
         verdict가 `unverifiable`이 *아니고* `client_is_correct`가 제출돼 있으면 클라 보고
         (`is_correct`)와 서버 판정(`verdict.state == "pass"`)을 대조해 불일치를 센다.
         `client_is_correct`가 `None`(레거시 미채점 행)이면 verdict는 집계하되 대조는
         건너뛴다(비교 불능 — mismatch로도 non-mismatch로도 세지 않는다).
    """
    total = len(records)
    not_derivable = 0
    verdict_counts: dict[str, int] = {"pass": 0, "fail": 0, "unverifiable": 0}
    mismatch = 0
    reason_counts: dict[str, int] = {
        "no_problem": 0,
        "no_student_answer": 0,
        "no_verify_input": 0,
        "parse_error": 0,
        "multi_symbol": 0,
    }

    for record in records:
        if record.problem is None:
            not_derivable += 1
            reason_counts["no_problem"] += 1
            continue
        verdict, reason = _grade_attempt_with_reason(record.problem, record.student_answer)
        if verdict is None:
            not_derivable += 1
            if reason is not None:
                reason_counts[reason] += 1
            else:
                # `_grade_attempt_with_reason`은 None verdict에 항상 사유를 준다.
                reason_counts["no_verify_input"] += 1
            continue
        verdict_counts[verdict.state] = verdict_counts.get(verdict.state, 0) + 1
        if verdict.state == "unverifiable":
            # 교수학 금기(acceptance②) — 판정 불가는 판정 불가. 오답/불일치로 강등 금지.
            continue
        if record.client_is_correct is None:
            continue  # 비교 불능(레거시 미채점) — mismatch 대상 아님.
        server_says_correct = verdict.state == "pass"
        if record.client_is_correct != server_says_correct:
            mismatch += 1

    return ShadowGradingReport(
        total_attempts=total,
        not_derivable_count=not_derivable,
        verifiable_count=total - not_derivable,
        verdict_counts=verdict_counts,
        client_grade_mismatch_count=mismatch,
        not_derivable_reason_counts=reason_counts,
    )


# ──────────────────────────────────────────────────────────────────────────
# 채점 가능성 상한 — 코퍼스 정적 리포트(REC-05, attempt 무관·순수 코어)
# ──────────────────────────────────────────────────────────────────────────
GradabilityBucket = Literal[
    "selectable_exact_match",
    "numeric_short_answer_candidate",
    "condition_formal_derivable",
    "unclassified",
]

_GRADABILITY_BUCKETS: tuple[GradabilityBucket, ...] = get_args(GradabilityBucket)

# 식(자유서술 수식)은 정규화 규칙이 없어 제외 — B버킷은 수치 3종만(REC-05 §2 G1 정의 그대로).
_NUMERIC_ANSWER_FORMATS: frozenset[AnswerFormat] = frozenset(
    {AnswerFormat.자연수, AnswerFormat.실수, AnswerFormat.분수}
)


def _classify_gradability_with_reason(
    problem: Problem,
) -> tuple[GradabilityBucket, _UnclassifiedReason | None]:
    """문항 1건 → (버킷, unclassified 사유). 내부 집계용(acceptance⑤)."""
    if problem.choices and problem.answer and problem.answer in problem.choices:
        return "selectable_exact_match", None
    derived, reason = _derive_verify_inputs_with_reason(problem)
    if derived is not None:
        return "condition_formal_derivable", None
    # `derive_verify_inputs`가 None인 상황에서만 unclassified 사유를 결정한다.
    unclassified_reason: _UnclassifiedReason
    if reason == "no_verify_input":
        # DB conditions_parsed도 없고 코퍼스 verify 블록도 없음.
        unclassified_reason = "no_verify_block"
    else:
        # `_derive_verify_inputs_with_reason`이 반환하는 나머지 사유는
        # `_NotDerivableReason`과 `_UnclassifiedReason`이 겹치는 영역다.
        unclassified_reason = cast(_UnclassifiedReason, reason)
    if (
        problem.question_format == QuestionFormat.단답형
        and problem.answer_format in _NUMERIC_ANSWER_FORMATS
    ):
        return "numeric_short_answer_candidate", None
    return "unclassified", unclassified_reason


def classify_gradability(problem: Problem) -> GradabilityBucket:
    """문항 1건 → 채점 가능성 버킷(순수·하드 우선순위 A→C→B→unclassified — 상호배타 계약).

    - **A**(`selectable_exact_match`): `choices` 보유 ∧ `answer` 보유 ∧ `answer`가 `choices`
      원소와 문자열 일치 — 서버 채점이 자명(정확일치 1회 비교).
    - **C**(`condition_formal_derivable`): `derive_verify_inputs`가 성공 —
      `Problem.conditions_parsed[*].formal` 또는 코퍼스 `verify.{conditions,answer_map}`
      (NLP-05)에서 파생. symbolic 검산이 가능한 문항으로, 단순 '수치 단답 후보'보다
      정확한 채점 경로다.
    - **B**(`numeric_short_answer_candidate`): `question_format`이 단답형이고 `answer_format`이
      수치 3종(`자연수`/`실수`/`분수`) 중 하나 — 정규화 규칙(권위는 SymPy) 도입 시 채점 가능.
      코퍼스 verify 블록으로 이미 symbolic 파생 가능한 문항은 C로 계상한다.
    - 그 외 **unclassified**: 셋 다 불성립. `choices`는 있는데 `answer`가 그 안에 없는
      데이터 이상치도 A로 오분류되지 않고 여기로 정직하게 떨어진다(조용한 은폐 금지).

    우선순위는 하드 계약이다 — A와 C를 동시에 만족하는 문항도 A로 계상한다(선택형이 더
    자명한 채점이므로). NLP-05 이후 C가 B보다 우선: symbolic 파생 가능한 문항은
    '후보'가 아닌 실제 검산 경로가 있음.
    """
    bucket, _reason = _classify_gradability_with_reason(problem)
    return bucket


@dataclass(slots=True, frozen=True)
class GradabilityCeilingReport:
    """코퍼스 전량의 채점 가능성 버킷 집계(불변) — 4버킷 합은 항상 `total_problems`와 같다.

    NLP-05 — `unclassified_reason_counts`가 unclassified 버킷으로 떨어진 문항의
    세부 원인(`no_verify_block`, `parse_error`, `multi_symbol`)을 계수한다. 이 합은
    `bucket_counts["unclassified"]`와 같다.
    """

    total_problems: int
    bucket_counts: dict[GradabilityBucket, int] = field(default_factory=dict)
    # NLP-05 — unclassified 세부 사유(acceptance⑤).
    unclassified_reason_counts: dict[str, int] = field(default_factory=dict)

    def bucket_rate(self, bucket: GradabilityBucket) -> float | None:
        """버킷 비율. `total_problems == 0`이면 `None`(분모 없는 0 금지)."""
        if self.total_problems == 0:
            return None
        return self.bucket_counts.get(bucket, 0) / self.total_problems

    def to_json(self) -> dict[str, Any]:
        return gradability_report_to_json(self)


def build_gradability_ceiling_report(problems: Sequence[Problem]) -> GradabilityCeilingReport:
    """문항 목록 → `GradabilityCeilingReport`(순수·부작용 0). 각 문항을 정확히 한 버킷에 계상."""
    counts: dict[GradabilityBucket, int] = dict.fromkeys(_GRADABILITY_BUCKETS, 0)
    reason_counts: dict[str, int] = {
        "no_verify_block": 0,
        "parse_error": 0,
        "multi_symbol": 0,
    }
    for problem in problems:
        bucket, reason = _classify_gradability_with_reason(problem)
        counts[bucket] += 1
        if reason is not None:
            reason_counts[reason] += 1
    return GradabilityCeilingReport(
        total_problems=len(problems),
        bucket_counts=counts,
        unclassified_reason_counts=reason_counts,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def render_report(report: ShadowGradingReport) -> str:
    """리포트를 마크다운으로 렌더(순수·입력 외 계산 없음).

    acceptance④ 리터럴 문구: 불일치는 **"검산 가능 표본 N건 중 M건"**으로 표시한다 — M이
    0이어도 분모 없는 "0건"으로 위장하지 않는다. `verifiable_count == 0`(표본 자체가 없음)은
    다른 문장으로 구분한다(둘 다 "0건"으로 뭉개면 "관측이 안 됨"과 "관측했더니 0건"이
    구별 안 된다).
    """
    lines = [
        "# 서버측 답안 채점 shadow 리포트 (NLP-02)",
        "",
        "> 관측 전용 리포트다 — BKT/숙달 전파 입력은 여전히 클라이언트 보고 `is_correct`다"
        '(권위 이관 아님·Kiki 결정 2026-07-31 "측정 없는 도입 없음").',
        "",
        f"- 총 attempt: **{report.total_attempts}**",
        f"- 파생 불가(재료 없음 — conditions/formal 미보유·다중 미지수·student_answer 없음 등): "
        f"**{report.not_derivable_count}**",
        f"- 검산 가능 표본: **{report.verifiable_count}**",
        "",
        "## 3상태 분포 (검산 가능 표본 내)",
        "",
        f"- pass: {report.verdict_counts.get('pass', 0)}",
        f"- fail: {report.verdict_counts.get('fail', 0)}",
        f"- unverifiable: {report.verdict_counts.get('unverifiable', 0)}",
        "",
        "## 파생 불가 사유 (NLP-05)",
        "",
    ]
    for key in (
        "no_problem",
        "no_student_answer",
        "no_verify_input",
        "parse_error",
        "multi_symbol",
    ):
        count = report.not_derivable_reason_counts.get(key, 0)
        lines.append(f"- {key}: {count}")
    lines.append("")
    lines.append("## 클라이언트 ↔ 서버 불일치 (이중 회계)")
    lines.append("")
    if report.verifiable_count == 0:
        lines.append("- 검산 가능 표본 0건 — 불일치율 측정 불가(데이터없음, 0%로 위장하지 않음).")
        if report.verifiable_zero_reason == "no_sample":
            lines.append(
                "  - 원인: 표본 없음(attempt 0행) — `POST /v1/me/attempts`가 아직 호출되지 않음."
            )
        else:
            lines.append(
                "  - 원인: 파생 가능 문항 0건(코퍼스 `conditions_parsed[*].formal` 전건 결측) "
                "— 표본이 있어도 채점 불가(REC-05 `--mode ceiling` 리포트 참조)."
            )
    else:
        rate = report.mismatch_rate
        rate_text = f"{rate:.2%}" if rate is not None else "데이터없음"
        lines.append(
            f"- 검산 가능 표본 {report.verifiable_count}건 중 "
            f"{report.client_grade_mismatch_count}건 불일치({rate_text})."
        )
        uv_rate = report.unverifiable_rate
        uv_text = f"{uv_rate:.2%}" if uv_rate is not None else "데이터없음"
        lines.append(
            f"- unverifiable 비율(이 기능의 실효 커버리지): {uv_text} — 낮을수록 "
            '"클라이언트를 믿어도 되는가" 판단 재료가 더 신뢰할 만하다.'
        )
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: ShadowGradingReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(분모 없는 비율은 `None` 그대로 보존)."""
    return {
        "total_attempts": report.total_attempts,
        "not_derivable_count": report.not_derivable_count,
        "verifiable_count": report.verifiable_count,
        "verdict_counts": dict(report.verdict_counts),
        "client_grade_mismatch_count": report.client_grade_mismatch_count,
        "mismatch_rate": report.mismatch_rate,
        "unverifiable_rate": report.unverifiable_rate,
        "verifiable_zero_reason": report.verifiable_zero_reason,
        "not_derivable_reason_counts": dict(report.not_derivable_reason_counts),
    }


_GRADABILITY_BUCKET_LABELS: dict[GradabilityBucket, str] = {
    "selectable_exact_match": "A. 선택형 정확일치",
    "numeric_short_answer_candidate": "B. 수치 단답 후보",
    "condition_formal_derivable": "C. 조건 기반 symbolic 파생",
    "unclassified": "미분류(데이터 품질 이상치 후보)",
}


def render_gradability_ceiling_report(report: GradabilityCeilingReport) -> str:
    """채점 가능성 상한 리포트를 마크다운으로 렌더(순수). C=0은 "파생 불가"로 명시한다
    (acceptance① — "0건 통과"가 아니라 파생 불가 사유를 적는다. 분모 없는 0 금지 승계).
    """
    lines = [
        "# 코퍼스 채점 가능성 상한 리포트 (REC-05)",
        "",
        "> 관측 전용 리포트다 — 신규 스키마·마이그레이션·클라 배선·권위 이관 0. exit 게이트 "
        "아님(항상 exit 0). attempt와 무관하게 코퍼스 전량만으로 산출된다.",
        "",
        f"- 코퍼스 전체 문항: **{report.total_problems}**",
        "",
        "## 버킷별 채점 가능성 (상호배타 — 합은 항상 전체 문항 수)",
        "",
    ]
    if report.total_problems == 0:
        lines.append("- 코퍼스 0건 — 관측 불가(분모 없음, 0%로 위장하지 않음).")
        lines.append("")
        return "\n".join(lines)

    for bucket in _GRADABILITY_BUCKETS:
        count = report.bucket_counts.get(bucket, 0)
        rate = report.bucket_rate(bucket)
        rate_text = f"{rate:.1%}" if rate is not None else "데이터없음"
        label = _GRADABILITY_BUCKET_LABELS[bucket]
        if bucket == "condition_formal_derivable" and count == 0:
            lines.append(
                f"- {label}: **{count} / {report.total_problems}** — 파생 불가(formal 전건 결측)"
            )
        else:
            lines.append(f"- {label}: **{count} / {report.total_problems}** ({rate_text})")
    lines.append("")
    lines.append("## 미분류 사유 (NLP-05)")
    lines.append("")
    for key in ("no_verify_block", "parse_error", "multi_symbol"):
        count = report.unclassified_reason_counts.get(key, 0)
        lines.append(f"- {key}: {count}")
    lines.append("")
    return "\n".join(lines)


def gradability_report_to_json(report: GradabilityCeilingReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(분모 0이면 `bucket_rates` 전부 `None`)."""
    return {
        "total_problems": report.total_problems,
        "bucket_counts": {b: report.bucket_counts.get(b, 0) for b in _GRADABILITY_BUCKETS},
        "bucket_rates": {b: report.bucket_rate(b) for b in _GRADABILITY_BUCKETS},
        "unclassified_reason_counts": {
            r: report.unclassified_reason_counts.get(r, 0) for r in get_args(_UnclassifiedReason)
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 접속·출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2


async def _run_shadow(args: argparse.Namespace) -> ShadowGradingReport:
    # lazy import — CLI를 실제로 실행할 때만 DB 세션 팩토리를 물게 한다(다른 함수의
    # 모듈 top-level import는 순수 유지).
    from whymath_backend.db.session import get_session

    async for session in get_session():
        records = await fetch_attempt_records(session, user_id=args.user_id, limit=args.limit)
        return build_report(records)
    raise RuntimeError("DB 세션을 얻지 못함")  # pragma: no cover — get_session은 항상 1회 yield


async def _run_ceiling(args: argparse.Namespace) -> GradabilityCeilingReport:
    from whymath_backend.db.session import get_session

    async for session in get_session():
        problems = await fetch_all_problems(session)
        return build_gradability_ceiling_report(problems)
    raise RuntimeError("DB 세션을 얻지 못함")  # pragma: no cover — get_session은 항상 1회 yield


def main(argv: list[str] | None = None) -> int:
    """CLI — `--mode shadow`(기본): DB에서 attempt를 읽어 shadow 채점 리포트를 출력.
    `--mode ceiling`: 코퍼스 전량을 채점 가능성 3버킷으로 분류(REC-05, attempt 무관). 둘 다
    **게이트가 아니다**(항상 exit 0, DB 접속 실패만 exit 2).

    불일치·unverifiable 비율이 얼마든 exit 0이다 — 권위 이관 여부는 이 수치를 본 사람이
    판단한다(Kiki 결정 2026-07-31 "측정 없는 도입 없음" — 이 CLI는 그 측정만 낸다).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.attempt_grading_shadow_report",
        description=(
            "POST /v1/me/attempts 적재분을 verify_answer로 shadow 재검산해 클라/서버 불일치·"
            "unverifiable 비율을 관측하거나(--mode shadow, 기본), 코퍼스 전량의 채점 가능성 "
            "상한을 관측한다(--mode ceiling). 둘 다 NLP-02/REC-05·관측 전용·게이트 아님."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("shadow", "ceiling"),
        default="shadow",
        help="shadow(기본, 회귀 0) 또는 ceiling(REC-05 코퍼스 정적 리포트)",
    )
    parser.add_argument(
        "--user-id",
        type=uuid.UUID,
        default=None,
        help="특정 사용자로 스코핑(--mode shadow 전용·선택·기본 전량)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="조회할 attempt 상한(--mode shadow 전용·선택)"
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    if args.mode == "ceiling" and (args.user_id is not None or args.limit is not None):
        print(
            "--mode ceiling에서는 --user-id/--limit이 무시됩니다(코퍼스 전량 관측).",
            file=sys.stderr,
        )

    try:
        if args.mode == "ceiling":
            ceiling_report = asyncio.run(_run_ceiling(args))
        else:
            shadow_report = asyncio.run(_run_shadow(args))
    except Exception as exc:  # noqa: BLE001 — DB 접속 실패 등은 타입명과 함께 보고 후 exit 2
        print(f"입력/접속 오류({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    if args.mode == "ceiling":
        print(render_gradability_ceiling_report(ceiling_report))
        json_payload = gradability_report_to_json(ceiling_report)
    else:
        print(render_report(shadow_report))
        json_payload = report_to_json(shadow_report)

    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(json_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
