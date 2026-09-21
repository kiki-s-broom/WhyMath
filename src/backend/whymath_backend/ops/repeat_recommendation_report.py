"""반복 추천 가시화 리포트 — 같은 학생이 몇 번을 불러도 같은 문항을 받는가 (REC-06).

배경 (왜 이 모듈이 필요한가)
----------------------------
`GET /v1/me/next-problem`은 세 가지가 겹쳐 **연속 호출 시 같은 문항 1건을 고정 반환**한다
(`docs/architecture/ai_recommendation_module_gap_review_2.md` §2 G2 — 전부 소스로 확정되는 사실):

  ① θ 추정   — 채점 이력이 0행이면 `estimate_ability([])`가 초기값을 그대로 돌려준다(θ=0 고정)
  ② 출제 이력 제외 — `attempted_ids`의 공급원인 `problem_attempt`가 0행이라 제외가 **0건**
     (집합이 비어 `WHERE ... NOT IN`이 아예 붙지 않는다)
  ③ 선택     — `l2.select_weighted_item`은 가중 정보량의 **결정론 argmax**(동률=낮은 인덱스)

즉 학생이 "다음 문제"를 눌러도 진도가 만들어지지 않는다. 실기기 시연에서 즉시 보이는 형태인데도
지금까지 *수치로* 관측된 적이 없었다. 이 모듈은 그 진도 폭을 실측하고, **반복의 원인을 서로 다른
값으로 갈라** 보고한다.

이 리포트가 하지 않는 것 (범위 밖 동결 — acceptance⑤)
--------------------------------------------------
노출 통제(randomesque top-k)·다양성 가중·학생 축 노출 이력 좌석 **신설을 하지 않는다**. 다양성은
"이 학생에게 최근 무엇을 추천했는가"를 읽을 수 있어야 성립하는데 그 이력원이 0이기 때문이다
(`evidence_event`에 `user_id` 컬럼이 없고 `session_id`는 추천마다 새 `uuid4()` — 2차 재점검 G3).
입력이 없는 파이프라인을 붙이는 것은 증상 가리기다. 이 슬라이스는 **가시화까지**이고, 서빙
동작 변경은 후보 정렬의 2차 키 동결 하나뿐이다(아래).

"진도 폭"을 어떻게 재는가 — 합성 프로브(라이브 학생 데이터 0)
------------------------------------------------------------
`problem_attempt`가 0행이므로 라이브 학생 표본을 기다리면 이 리포트는 영원히 값을 못 낸다
(`REC-05`가 실측한 "만들었는데 커버리지가 0" 함정과 같은 구조). 그래서 프로브는 **합성**이다:

  - θ는 콜드스타트 값을 `l2.estimate_ability([])`에서 *유도*한다(상수 하드코딩 0). 실제 학생
    전원이 지금 이 θ를 받고 있으므로 이것이 관측해야 할 바로 그 조건이다.
  - 후보 풀은 서빙 경로와 **같은 함수**로 조립한다 — `api.me.candidate_pool_conditions()`
    (노출 게이트 3축)와 `api.me.candidate_pool_order_by(θ)`(|b−θ| → problem_id)를 import한다.
    리포트가 후보 조회를 자기 방식으로 다시 짜면 "리포트가 보는 풀"과 "학생이 받는 풀"이 조용히
    갈라져 측정이 서빙을 설명하지 못한다(단일 진실 원천 — 유지보수 지옥 방어).
  - 선택은 서빙 기본값(`purpose=diagnosis`·`prioritize_weak_concepts=false`)과 같은
    `l2.select_weighted_item(θ, items)`(가중 없음)이다.

두 회귀(regime)를 각각 N회 돌려 **서로 다른 두 수**를 낸다:

  실태(observed)   호출 사이에 제외 축으로 아무것도 들어오지 않는다 = 현행 그대로. 진도 폭이
                   1이면 그것이 학생이 실제로 겪는 상태다.
  반사실(feedback) 반환된 문항이 다음 호출의 제외 집합에 들어간다 = 제외 축이 작동했을 때의
                   진도 폭 **상한**. 실측이 아니라 계산된 대조군이며 리포트가 그렇게 표기한다.

원인 구분 — "제외 축 0행"과 "풀이 실제로 1건"은 절대 같은 값이면 안 된다
--------------------------------------------------------------------
두 상태는 처방이 정반대다(전자는 attempt 루프를 닫아야 풀리고, 후자는 루프를 닫아도 안 풀린다).
`l2/axis_exclusions.py`가 추천 좌석의 탈락 사유를 카운트로 갈라 놓은 것과 같은 이유로, 여기서도
반복 사유를 상호배타 코드로 계상한다(침묵 실패 금지 — 조용히 같은 값으로 뭉개지 않는다):

  `empty_candidate_pool`      후보 풀 0건 — 추천 자체가 null(반복 이전의 문제)
  `candidate_pool_singleton`  풀이 실제로 1건 — 제외 축을 고쳐도 반복은 안 풀린다
  `no_attempt_exclusion`      풀은 여럿인데 제외 축 입력원(`problem_attempt`)이 0행
  `deterministic_argmax_tie`  입력원은 실재하는데도 반복 — 결정론 argmax가 같은 최댓값을 고른다

"반복 없음" 코드는 두지 않는다. 실태 회귀에서 진도 폭이 1을 넘는 일은 **구성상 일어날 수 없기**
때문이다(같은 인자로 같은 순수 함수를 N번 부른다) — 그리고 그것이 이 리포트가 보고하는 사실
자체다. 도달 불가능한 분기를 "혹시 몰라" 남기면 그 분기는 영원히 검증되지 않는 죽은 코드가 된다.

집중도 — 후보 풀 50의 개념·유형 쏠림
------------------------------------
진도 폭이 열려도 풀이 한 개념·한 유형에 쏠려 있으면 학생 체감은 여전히 "같은 문제"다. 개념 축은
DB(`problem_concept` × `concept.code`, 평가 역할만)에서, 유형 축은 **코퍼스 JSONL**에서 읽는다 —
`problem_type_codes`(S3-27)는 스키마에는 있으나 **ORM 컬럼이 아니라 DB에 존재하지 않기 때문**이다
(`schema/problem.py` 주석의 2026-08-11 R3 §정정-4). 그래서 유형 축은 "코퍼스에 없어서 못 봤다"
(`unresolved`)와 "코퍼스에 있는데 태그가 비었다"(`unlabelled`)를 **서로 다른 값**으로 낸다.

실행
----
    python -m whymath_backend.ops.repeat_recommendation_report
    python -m whymath_backend.ops.repeat_recommendation_report --calls 10 --json out/repeat.json

종료 코드: 0=성공(진도 폭이 1이어도 게이트가 아니다) / 2=실행 오류(DB 접속 실패·코퍼스 파손 등
전제 미충족). 실패는 예외를 삼키지 않고 **타입명**과 함께 stderr에 보고한다(침묵 실패 금지 —
`str(exc)`엔 DSN 등 환경값이 섞일 수 있어 메시지 앞에 타입명을 싣는다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.concept import Concept, ProblemConcept
from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.l2.ability_estimation import resolve_item_difficulty_b
from whymath_backend.l2.irt import IrtItem, estimate_ability, item_information, select_weighted_item

# 서빙 경로와 후보 조회를 공유한다(모듈 docstring "합성 프로브" 참조) — 재구현 금지.
# EOS-19: 후보 풀 정의가 `api/me.py`(L5)에서 `l2/next_problem_selection.py`로 내려갔다.
# 리포트가 *서빙과 같은 풀*을 보는 것이 이 import의 존재 이유이므로(REC-06), 재노출 경유가
# 아니라 소유 모듈을 직접 가리킨다.
from whymath_backend.l2.next_problem_selection import (
    CANDIDATE_POOL_SIZE as _CANDIDATE_POOL_SIZE,
)
from whymath_backend.l2.next_problem_selection import (
    candidate_pool_conditions,
    candidate_pool_order_by,
)
from whymath_backend.schema.enums import ASSESSED_ROLES

__all__ = [
    "AXIS_CONCEPT",
    "AXIS_PROBLEM_TYPE",
    "CAUSE_CANDIDATE_POOL_SINGLETON",
    "CAUSE_DETAIL",
    "CAUSE_DETERMINISTIC_ARGMAX_TIE",
    "CAUSE_EMPTY_CANDIDATE_POOL",
    "CAUSE_NO_ATTEMPT_EXCLUSION",
    "AxisConcentration",
    "CandidateRow",
    "ProblemTypeIndex",
    "RepeatProbeInputs",
    "RepeatReport",
    "build_repeat_report",
    "cold_start_theta",
    "default_corpus_root",
    "dump_json",
    "fetch_probe_inputs",
    "load_problem_type_index",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_RUNTIME_ERROR = 2

_DEFAULT_CALLS = 5

# 코퍼스 위치·파일명 관례 — `harness/problem_bank_coverage.py`와 동일(신설 관례 0).
_CORPUS_DIR_GLOB = "problem_bank*"
_CORPUS_FILE_NAME = "problems.jsonl"

AXIS_CONCEPT = "concept"
AXIS_PROBLEM_TYPE = "problem_type"

# ── 반복 원인 코드(상호배타) — 모듈 docstring "원인 구분" 참조 ────────────────────────────
CAUSE_EMPTY_CANDIDATE_POOL = "empty_candidate_pool"
CAUSE_CANDIDATE_POOL_SINGLETON = "candidate_pool_singleton"
CAUSE_NO_ATTEMPT_EXCLUSION = "no_attempt_exclusion"
CAUSE_DETERMINISTIC_ARGMAX_TIE = "deterministic_argmax_tie"

CAUSE_DETAIL: dict[str, str] = {
    CAUSE_EMPTY_CANDIDATE_POOL: (
        "후보 풀 0건 — 추천 자체가 null이라 반복 이전의 문제다. 노출 게이트 3축(난이도 라벨·"
        "저작권 출처·review_status=approved) 중 어디서 전멸했는지는 후보 모집단 수치로 가른다."
    ),
    CAUSE_CANDIDATE_POOL_SINGLETON: (
        "후보 풀이 실제로 1건 — 제외 축(attempt)을 고쳐도 반복은 풀리지 않는다. 처방은 공급"
        "(후보 모집단 확대)이지 루프가 아니다."
    ),
    CAUSE_NO_ATTEMPT_EXCLUSION: (
        "제외 축 입력 0행 — 후보는 여럿인데 `problem_attempt`가 0행이라 `attempted_ids`가 항상 "
        "공집합이고, 그래서 호출 사이에 아무것도 배제되지 않는다. 어떤 학생에게도 구조적으로 "
        "제외가 걸리지 않는다는 뜻이다(전역 0행). 처방은 attempt 루프를 닫는 것."
    ),
    CAUSE_DETERMINISTIC_ARGMAX_TIE: (
        "제외 축 입력원은 실재하는데도 반복 — 이 프로브의 제외 집합이 비어 있어 결정론 argmax"
        "(동률=낮은 인덱스)가 매번 같은 최댓값을 고른다. 동률 상위 건수를 함께 본다."
    ),
}


def default_corpus_root() -> Path:
    """`data/corpus` 저장소 정본 경로 — `ops/provenance_audit.default_corpus_root`와 동일
    관용구(`parents[4]`: ops/ → whymath_backend/ → backend/ → src/ → repo root)."""
    return Path(__file__).resolve().parents[4] / "data" / "corpus"


def cold_start_theta() -> float:
    """콜드스타트 θ — 채점 이력 0행일 때 서빙이 쓰는 값을 `l2`에서 *유도*한다(상수 하드코딩 0).

    `api/me._load_attempt_history_state`가 응답 0건에서 `estimate_ability([])`를 부르는 것과
    같은 호출이다. 이 값이 바뀌면 리포트도 자동으로 따라간다.
    """
    return estimate_ability([])


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 — 유형 축(problem_type_codes)은 DB에 없다(모듈 docstring "집중도" 참조).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ProblemTypeIndex:
    """코퍼스 유형 축 인덱스 + 그 인덱스가 *덮지 못한* 몫(분모의 출처를 함께 낸다).

    `missing_id_total`은 결함이 아니라 코퍼스의 실제 형태다 — `problem_bank_v1` 4건은
    `problem_id` 없이 `slug`만 갖고 있고, DB의 PK는 적재 시 `ON CONFLICT(slug)`로 생성·안정화된다
    (`l1/problem_bank/populate.py`: "problem_id는 코퍼스에 없으면 매번 새로 생성"). 즉 그 레코드는
    **id로 조인할 수 없다**. 0으로 뭉개지 않고 세어 리포트에 싣는다.
    """

    by_problem_id: dict[uuid.UUID, tuple[str, ...]]
    record_total: int
    missing_id_total: int


def load_problem_type_index(corpus_root: Path) -> ProblemTypeIndex:
    """`data/corpus/problem_bank*/problems.jsonl` → `problem_id → problem_type_codes`.

    파손은 조용히 넘기지 않는다 — JSON 파싱 실패·레코드 형태 이상(object 아님·id 타입 이상·
    codes가 배열 아님)은 예외로 올려 CLI가 exit 2로 보고한다(빈 인덱스를 돌려주면 "유형 미태깅
    100%"라는 **거짓 관측**이 된다). 반면 `problem_id` 부재는 파손이 아니라 코퍼스의 정상 형태라
    세어서 보고한다(`ProblemTypeIndex.missing_id_total`). 디렉터리 자체가 없으면 빈 인덱스이고,
    그 사실은 `corpus_problem_total=0`으로 리포트에 드러난다.
    """
    index: dict[uuid.UUID, tuple[str, ...]] = {}
    record_total = 0
    missing_id_total = 0
    if not corpus_root.is_dir():
        return ProblemTypeIndex(by_problem_id=index, record_total=0, missing_id_total=0)
    for corpus_dir in sorted(corpus_root.glob(_CORPUS_DIR_GLOB)):
        path = corpus_dir / _CORPUS_FILE_NAME
        if not path.is_file():
            continue
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise TypeError(
                    f"{path.name}:{line_no} 레코드가 object가 아님(type={type(obj).__name__})"
                )
            record_total += 1
            raw_id = obj.get("problem_id")
            codes = obj.get("problem_type_codes") or []
            if not isinstance(codes, list):
                raise TypeError(
                    f"{path.name}:{line_no} problem_type_codes가 배열이 아님"
                    f"(type={type(codes).__name__})"
                )
            if raw_id is None:
                missing_id_total += 1
                continue
            if not isinstance(raw_id, str):
                raise TypeError(
                    f"{path.name}:{line_no} problem_id가 문자열이 아님"
                    f"(type={type(raw_id).__name__})"
                )
            index[uuid.UUID(raw_id)] = tuple(sorted(str(c) for c in codes))
    return ProblemTypeIndex(
        by_problem_id=index, record_total=record_total, missing_id_total=missing_id_total
    )


# ──────────────────────────────────────────────────────────────────────────
# DB 접속 경계 — 쿼리 4회(전부 SQLAlchemy Core/ORM 쿼리빌더, 원시 SQL 0).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class CandidateRow:
    """후보 풀 1건 — 서빙이 뽑는 3컬럼 + 집중도 축 2종(개념·유형)."""

    problem_id: uuid.UUID
    difficulty_overall: float | None
    irt_difficulty_b: float | None
    concept_codes: tuple[str, ...] = ()
    problem_type_codes: tuple[str, ...] = ()
    # 코퍼스에서 이 problem_id를 찾았는가 — False면 유형 축이 '미태깅'이 아니라 '미조인'이다.
    in_corpus: bool = False


@dataclass(slots=True, frozen=True)
class RepeatProbeInputs:
    """DB·코퍼스에서 실측한 원시 입력 — `build_repeat_report`(순수)의 유일한 입력."""

    theta: float
    pool: tuple[CandidateRow, ...]
    attempt_axis_row_total: int
    candidate_population_total: int
    corpus_problem_total: int
    corpus_missing_id_total: int = 0


async def fetch_probe_inputs(
    session: AsyncSession,
    *,
    theta: float,
    problem_type_index: ProblemTypeIndex,
    pool_size: int = _CANDIDATE_POOL_SIZE,
) -> RepeatProbeInputs:
    """쿼리 4회로 프로브 입력을 실측한다. 쿼리 순서는 테스트와의 계약이므로 바꾸지 않는다.

    ① 제외 축 입력원 크기 — `problem_attempt` 전체 행 수. 0이면 어떤 학생의 `attempted_ids`도
       반드시 공집합이다(구조적 사실이지 추론이 아니다).
    ② 후보 모집단 — 노출 게이트 3축을 통과하는 문항 전체 수. 풀 50이 *잘린 것*인지 모집단
       자체가 작은 것인지를 가르는 분모다.
    ③ 후보 풀 — 서빙과 **같은** WHERE·ORDER BY·LIMIT. 합성 프로브는 이력이 없으므로 attempt·
       형제 배제 조건은 붙지 않는다(현행 학생과 동일 조건).
    ④ 후보의 평가 개념 코드 — `ASSESSED_ROLES`만(서빙의 약점 가중과 같은 역할 집합).

    후보가 0건이어도 ④를 건너뛰지 않는다(쿼리 4회 고정 — 테스트 큐 계약 단순화). `IN ()`은
    빈 결과를 돌려줄 뿐이라 부작용이 없다.
    """
    attempt_total = int(
        (await session.execute(select(func.count()).select_from(ProblemAttempt))).scalar_one()
    )

    population_total = int(
        (
            await session.execute(
                select(func.count()).select_from(Problem).where(*candidate_pool_conditions())
            )
        ).scalar_one()
    )

    pool_stmt = (
        select(Problem.problem_id, Problem.difficulty_overall, Problem.irt_difficulty_b)
        .where(*candidate_pool_conditions())
        .order_by(*candidate_pool_order_by(theta))
        .limit(pool_size)
    )
    pool_rows = (await session.execute(pool_stmt)).all()
    pool_ids = [row[0] for row in pool_rows]

    concept_stmt = (
        select(ProblemConcept.problem_id, Concept.code)
        .join(Concept, ProblemConcept.concept_id == Concept.concept_id)
        .where(
            ProblemConcept.problem_id.in_(pool_ids),
            ProblemConcept.role.in_(ASSESSED_ROLES),
        )
    )
    concepts_by_problem: dict[uuid.UUID, set[str]] = {}
    for problem_id, code in (await session.execute(concept_stmt)).all():
        concepts_by_problem.setdefault(problem_id, set()).add(str(code))

    by_id: Mapping[uuid.UUID, tuple[str, ...]] = problem_type_index.by_problem_id
    pool = tuple(
        CandidateRow(
            problem_id=problem_id,
            difficulty_overall=None if difficulty is None else float(difficulty),
            irt_difficulty_b=None if irt_b is None else float(irt_b),
            concept_codes=tuple(sorted(concepts_by_problem.get(problem_id, set()))),
            problem_type_codes=by_id.get(problem_id, ()),
            in_corpus=problem_id in by_id,
        )
        for problem_id, difficulty, irt_b in pool_rows
    )
    return RepeatProbeInputs(
        theta=theta,
        pool=pool,
        attempt_axis_row_total=attempt_total,
        candidate_population_total=population_total,
        corpus_problem_total=problem_type_index.record_total,
        corpus_missing_id_total=problem_type_index.missing_id_total,
    )


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 순수 코어(I/O 0·hermetic 검증 가능).
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class AxisConcentration:
    """한 축(개념·유형)의 후보 풀 쏠림 — 분모를 항상 함께 낸다.

    `labelled_problem_total`이 분모다. 한 문항이 라벨을 여러 개 가질 수 있으므로 분포 합계는
    분모를 넘을 수 있고(`top_share`도 그래서 1을 넘을 수 있다), 그 사실을 렌더가 명시한다.
    `unlabelled`(축 소스는 있는데 라벨이 빈 문항)과 `unresolved`(축 소스 자체를 못 찾은 문항)는
    **서로 다른 값**이다 — 뭉치면 "미태깅"과 "미조인"이 같은 얼굴이 된다.
    """

    axis: str
    labelled_problem_total: int
    unlabelled_problem_total: int
    unresolved_problem_total: int
    distinct_labels: int
    top_label: str | None
    top_count: int
    top_share: float | None
    distribution: dict[str, int]


def _build_concentration(
    axis: str,
    label_lists: Sequence[tuple[str, ...]],
    *,
    unresolved_problem_total: int,
) -> AxisConcentration:
    """라벨 목록(문항별) → 집중도(순수). 분모 0이면 `top_share`는 0.0이 아니라 None이다."""
    counter: Counter[str] = Counter()
    labelled = 0
    unlabelled = 0
    for codes in label_lists:
        if codes:
            labelled += 1
            counter.update(codes)
        else:
            unlabelled += 1
    # 동률은 라벨 사전순으로 고정한다(Counter.most_common은 삽입 순서 의존 — 결정론 확보).
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    top_label, top_count = ranked[0] if ranked else (None, 0)
    return AxisConcentration(
        axis=axis,
        labelled_problem_total=labelled,
        unlabelled_problem_total=unlabelled,
        unresolved_problem_total=unresolved_problem_total,
        distinct_labels=len(counter),
        top_label=top_label,
        top_count=top_count,
        top_share=(top_count / labelled) if labelled else None,
        distribution=dict(ranked),
    )


def _simulate_calls(
    theta: float, items: list[IrtItem], *, calls: int, feedback: bool
) -> tuple[int, ...]:
    """N회 연속 호출의 선택 인덱스 — 서빙 기본값과 같은 `select_weighted_item`(가중 없음).

    `feedback=False`(실태)면 호출 사이에 제외 집합이 비어 있어 매번 같은 인덱스가 나온다.
    `feedback=True`(반사실)면 직전 반환 문항이 제외 집합에 들어간다 = 제외 축이 작동했을 때의
    진도 폭 상한. 후보가 소진되면 그 시점에 멈춘다(빈 자리를 지어내지 않는다).
    """
    administered: set[int] = set()
    picks: list[int] = []
    for _ in range(calls):
        index = select_weighted_item(theta, items, administered=administered)
        if index is None:
            break
        picks.append(index)
        if feedback:
            administered.add(index)
    return tuple(picks)


def _top_score_tie_total(theta: float, items: list[IrtItem]) -> int:
    """가중 없는 정보량 최댓값을 공유하는 후보 수 — 결정론 argmax가 가른 동률 구간의 크기.

    이 값이 2 이상이면 "누가 뽑히는가"가 후보 **순서**로 결정된다는 뜻이고, 그 순서가 PG 임의
    였다는 것이 `candidate_pool_order_by`에 2차 키를 넣은 이유다. 후보 0건이면 0.
    """
    if not items:
        return 0
    scores = [item_information(theta, item) for item in items]
    best = max(scores)
    return sum(1 for score in scores if math.isclose(score, best, rel_tol=1e-12, abs_tol=1e-12))


@dataclass(slots=True, frozen=True)
class RepeatReport:
    """반복 추천 관측 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    theta: float
    calls: int
    candidate_pool_size: int
    candidate_population_total: int
    attempt_axis_row_total: int
    corpus_problem_total: int
    corpus_missing_id_total: int
    observed_selection: tuple[str, ...]
    observed_distinct_total: int
    feedback_selection: tuple[str, ...]
    feedback_distinct_total: int
    top_score_tie_total: int
    b_missing_total: int
    repeat_cause: str
    repeat_cause_detail: str
    concept_concentration: AxisConcentration
    problem_type_concentration: AxisConcentration


def _classify_repeat_cause(*, pool_size: int, attempt_axis_row_total: int) -> str:
    """반복 원인 1개(상호배타) — 판정 순서가 곧 배타성 정의다.

    ① 후보가 0이면 반복 이전에 추천 자체가 없다. ② 후보가 1건이면 제외 축을 고쳐도 반복은
    안 풀린다(공급 문제). ③ 후보가 여럿인데 제외 축 입력원이 0행이면 원인은 입력 미도달.
    ④ 입력원이 있는데도 반복이면 원인은 선택기의 결정론이다.

    판정에 `calls`를 쓰지 않는 것이 중요하다 — 반사실 진도 폭은 `min(calls, pool)`이라
    `calls=1`에서는 큰 풀도 1이 되고, 그것을 "풀이 1건"으로 읽으면 **호출 수가 원인을 바꾸는**
    가짜 판정이 된다. 원인은 풀 크기와 입력원 크기라는 상태값으로만 가른다.
    """
    if pool_size == 0:
        return CAUSE_EMPTY_CANDIDATE_POOL
    if pool_size == 1:
        return CAUSE_CANDIDATE_POOL_SINGLETON
    if attempt_axis_row_total == 0:
        return CAUSE_NO_ATTEMPT_EXCLUSION
    return CAUSE_DETERMINISTIC_ARGMAX_TIE


def build_repeat_report(inputs: RepeatProbeInputs, *, calls: int = _DEFAULT_CALLS) -> RepeatReport:
    """프로브 입력 → `RepeatReport`(순수·부작용 0). `calls`는 1 이상이어야 한다."""
    if calls < 1:
        raise ValueError(f"calls는 1 이상이어야 합니다(받은 값={calls})")
    theta = inputs.theta

    # 서빙과 동일한 b 결정(보정 b 우선·전문가 난이도 휴리스틱 폴백). SQL이 난이도 라벨 보유만
    # 후보로 뽑으므로 b가 None인 행은 원칙적으로 없지만, 0으로 뭉개지 않고 별도로 계상한다.
    items: list[IrtItem] = []
    kept: list[CandidateRow] = []
    b_missing = 0
    for row in inputs.pool:
        b = resolve_item_difficulty_b(row.irt_difficulty_b, row.difficulty_overall)
        if b is None:
            b_missing += 1
            continue
        items.append(IrtItem(difficulty=b))
        kept.append(row)

    observed = _simulate_calls(theta, items, calls=calls, feedback=False)
    feedback = _simulate_calls(theta, items, calls=calls, feedback=True)
    observed_ids = tuple(str(kept[i].problem_id) for i in observed)
    feedback_ids = tuple(str(kept[i].problem_id) for i in feedback)
    observed_distinct = len(set(observed_ids))
    feedback_distinct = len(set(feedback_ids))

    cause = _classify_repeat_cause(
        pool_size=len(kept),
        attempt_axis_row_total=inputs.attempt_axis_row_total,
    )
    return RepeatReport(
        theta=theta,
        calls=calls,
        candidate_pool_size=len(inputs.pool),
        candidate_population_total=inputs.candidate_population_total,
        attempt_axis_row_total=inputs.attempt_axis_row_total,
        corpus_problem_total=inputs.corpus_problem_total,
        corpus_missing_id_total=inputs.corpus_missing_id_total,
        observed_selection=observed_ids,
        observed_distinct_total=observed_distinct,
        feedback_selection=feedback_ids,
        feedback_distinct_total=feedback_distinct,
        top_score_tie_total=_top_score_tie_total(theta, items),
        b_missing_total=b_missing,
        repeat_cause=cause,
        repeat_cause_detail=CAUSE_DETAIL[cause],
        concept_concentration=_build_concentration(
            AXIS_CONCEPT,
            [row.concept_codes for row in inputs.pool],
            unresolved_problem_total=0,  # 개념 축은 DB 조인이라 '조회 불가' 상태가 없다
        ),
        problem_type_concentration=_build_concentration(
            AXIS_PROBLEM_TYPE,
            [row.problem_type_codes for row in inputs.pool if row.in_corpus],
            unresolved_problem_total=sum(1 for row in inputs.pool if not row.in_corpus),
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _share_text(share: float | None) -> str:
    return "측정 불가(분모 0)" if share is None else f"{share:.1%}"


def _concentration_lines(concentration: AxisConcentration, *, title: str) -> list[str]:
    lines = [
        f"### {title}",
        "",
        f"- 라벨 보유 문항(분모): **{concentration.labelled_problem_total}** · "
        f"라벨 없음(미태깅): {concentration.unlabelled_problem_total} · "
        f"축 조회 불가(미조인): {concentration.unresolved_problem_total}",
        f"- 서로 다른 라벨 수: **{concentration.distinct_labels}**",
        f"- 최다 라벨: **{concentration.top_label or '없음'}** "
        f"({concentration.top_count}건 · 분모 대비 {_share_text(concentration.top_share)})",
    ]
    if concentration.distribution:
        top = list(concentration.distribution.items())[:10]
        rendered = ", ".join(f"{label}={count}" for label, count in top)
        lines.append(f"- 분포(상위 {len(top)}): {rendered}")
        lines.append("  - 한 문항이 라벨을 여러 개 가질 수 있어 분포 합계는 분모를 넘을 수 있다.")
    return [*lines, ""]


def render_report(report: RepeatReport) -> str:
    """반복 추천 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    lines: list[str] = [
        "# 반복 추천 가시화 리포트 (REC-06)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(진도 폭이 1이어도 exit 0).",
        "> 라이브 학생 데이터를 쓰지 않는다(합성 프로브 + 코퍼스). 무작위화·다양성 가중은 넣지 "
        "않는다(범위 밖 동결).",
        "",
        "## 0. 프로브 조건",
        "",
        f"- θ(콜드스타트, `l2.estimate_ability([])`에서 유도): **{report.theta}**",
        f"- 연속 호출 수 N: **{report.calls}** (동일 조건·기본 파라미터 "
        "`purpose=diagnosis`·`prioritize_weak_concepts=false`)",
        f"- 후보 풀 크기: **{report.candidate_pool_size}** / 후보 모집단 "
        f"{report.candidate_population_total} (풀 상한 {_CANDIDATE_POOL_SIZE})",
        f"- 코퍼스 유형 인덱스: {report.corpus_problem_total}건 "
        f"(그중 problem_id 부재로 id 조인 불가 {report.corpus_missing_id_total}건 — "
        "적재 시 slug로 PK가 생성되는 레코드다. 파손이 아니라 코퍼스의 형태다)",
    ]
    if report.b_missing_total:
        lines.append(
            f"- ⚠️ b(난이도) 결정 불가로 제외된 후보: {report.b_missing_total}건 "
            "(난이도 라벨 보유만 후보이므로 원칙적으로 0이어야 한다)"
        )
    lines += [
        "",
        "## 1. 진도 폭 — N회 연속 호출에서 서로 다른 problem_id 수",
        "",
        f"- **실태(observed)**: {report.observed_distinct_total} / {report.calls}",
        f"- 반사실(제외 축이 작동했을 때의 상한): {report.feedback_distinct_total} / "
        f"{report.calls}",
        "  - 반사실은 *계산된 대조군*이다(실측 아님) — 반환 문항이 다음 호출의 제외 집합에 "
        "들어간다고 가정했을 때의 값이다.",
        "  - 실태 값이 1을 넘는 일은 구성상 없다(같은 인자로 같은 순수 함수를 N번 부른다). "
        "그 사실 자체가 이 리포트의 관측 결과이고, 아래 원인 코드가 *왜* 그런지를 가른다.",
        f"- 실태 반환 순서: {', '.join(report.observed_selection) or '(추천 없음)'}",
        "",
        "## 2. 반복 원인 (상호배타 — '제외 축 0행'과 '풀이 1건'은 서로 다른 값이다)",
        "",
        f"- 원인 코드: **{report.repeat_cause}**",
        f"- 해설: {report.repeat_cause_detail}",
        f"- 제외 축 입력원(`problem_attempt` 전체 행 수): **{report.attempt_axis_row_total}**",
        f"- 정보량 최댓값 동률 후보 수: **{report.top_score_tie_total}** "
        "(2 이상이면 후보 *순서*가 선택을 가른다 — 그래서 후보 정렬에 2차 키를 넣었다)",
        "",
        "## 3. 후보 풀 집중도",
        "",
    ]
    lines += _concentration_lines(report.concept_concentration, title="개념 축(평가 역할만)")
    lines += _concentration_lines(
        report.problem_type_concentration, title="유형 축(S3-27 problem_type_codes · 코퍼스)"
    )
    return "\n".join(lines)


def _concentration_to_json(concentration: AxisConcentration) -> dict[str, Any]:
    return {
        "axis": concentration.axis,
        "labelled_problem_total": concentration.labelled_problem_total,
        "unlabelled_problem_total": concentration.unlabelled_problem_total,
        "unresolved_problem_total": concentration.unresolved_problem_total,
        "distinct_labels": concentration.distinct_labels,
        "top_label": concentration.top_label,
        "top_count": concentration.top_count,
        "top_share": concentration.top_share,
        "distribution": concentration.distribution,
    }


def report_to_json(report: RepeatReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "probe": {
            "theta": report.theta,
            "calls": report.calls,
            "candidate_pool_size": report.candidate_pool_size,
            "candidate_population_total": report.candidate_population_total,
            "candidate_pool_size_cap": _CANDIDATE_POOL_SIZE,
            "corpus_problem_total": report.corpus_problem_total,
            "corpus_missing_id_total": report.corpus_missing_id_total,
            "b_missing_total": report.b_missing_total,
        },
        "progress_width": {
            "observed_distinct_total": report.observed_distinct_total,
            "observed_selection": list(report.observed_selection),
            "counterfactual_feedback_distinct_total": report.feedback_distinct_total,
            "counterfactual_feedback_selection": list(report.feedback_selection),
        },
        "repeat_cause": {
            "code": report.repeat_cause,
            "detail": report.repeat_cause_detail,
            "attempt_axis_row_total": report.attempt_axis_row_total,
            "top_score_tie_total": report.top_score_tie_total,
        },
        "concentration": {
            AXIS_CONCEPT: _concentration_to_json(report.concept_concentration),
            AXIS_PROBLEM_TYPE: _concentration_to_json(report.problem_type_concentration),
        },
    }


def dump_json(report: RepeatReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 세션 열고 닫기·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run(*, calls: int, theta: float, corpus_root: Path) -> RepeatReport:
    """코퍼스 인덱스를 읽고 세션을 열어 프로브를 실측한 뒤 리포트를 조립(조회 전용·쓰기 0)."""
    problem_type_index = load_problem_type_index(corpus_root)
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            inputs = await fetch_probe_inputs(
                session, theta=theta, problem_type_index=problem_type_index
            )
    finally:
        await dispose_engine()
    return build_repeat_report(inputs, calls=calls)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 반복 추천 관측 리포트를 stdout에 출력. **0=성공 / 2=실행 오류**(1 없음).

    진도 폭이 1이어도 exit 0이다(게이트 아님 — 머지를 막는 판정기가 아니다). exit 2는 DB 접속·
    코퍼스 파싱 등 실행 전제가 깨질 때만 쓰며, 예외를 삼키지 않고 **타입명**을 stderr에 남긴다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.repeat_recommendation_report",
        description=(
            "반복 추천 가시화 리포트(REC-06) — 동일 조건 N회 연속 호출의 진도 폭, 후보 풀의 "
            "개념·유형 집중도, 반복 원인 코드를 산출한다. 합성 프로브·코퍼스만 쓰므로 "
            "problem_attempt 0행에서도 값이 나온다. 결정론적 exit 0/2(게이트 아님)."
        ),
    )
    parser.add_argument(
        "--calls",
        type=int,
        default=_DEFAULT_CALLS,
        help=f"연속 호출 수 N(기본 {_DEFAULT_CALLS}·1 이상)",
    )
    parser.add_argument(
        "--theta",
        type=float,
        default=None,
        help="프로브 θ(미지정이면 콜드스타트 값 — 채점 이력 0행 학생이 실제로 받는 θ)",
    )
    parser.add_argument(
        "--corpus-root",
        dest="corpus_root",
        type=Path,
        default=None,
        help="코퍼스 루트(기본 data/corpus) — 유형 축 인덱스 원천",
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(
            _run(
                calls=args.calls,
                theta=cold_start_theta() if args.theta is None else float(args.theta),
                corpus_root=args.corpus_root or default_corpus_root(),
            )
        )
    except Exception as exc:  # noqa: BLE001 — 침묵 실패 금지: 실행 오류를 타입명과 함께 보고
        print(
            f"실행 오류 — 반복 추천 리포트 생성 실패({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return _EXIT_RUNTIME_ERROR

    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
