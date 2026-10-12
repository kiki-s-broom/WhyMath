"""문제은행 커버리지 리포트 CLI — 빌드타임 결정론 관측(LLM 0·DB 0·HTTP 0).

설계 정본: `docs/architecture/problem_bank_gap_review.md` §3 **D4**(품질 15축 ⑫ 커버리지 잔여
공백). 문제 코퍼스 전량을 스캔해 ⑴ 성취기준 대비 커버율·0커버 목록 ⑵ `unit_code` × 난이도 밴드
분포 매트릭스 ⑶ 코퍼스별·질문형식별 분해를 낸다. S4-01(초·중 확장)의 **저작 우선순위 입력**이며,
"관측 없는 확장 금지"의 관측 쪽을 담당한다.

**게이트가 아니다**(같은 harness 축의 `corpus_audit_eval`과의 결정적 차이):
`corpus_audit_eval`은 합격 로트 샘플링 *게이트*라 임계 초과 시 exit 1을 낸다. 이 모듈은
*관측 리포트*라 커버율이 아무리 낮아도 **exit 1을 내지 않는다** — 종료 코드는 성공(0)과
입력 오류(2·지정한 코퍼스/성취기준 파일 부재 등)만 구분한다. 커버율에 임계를 걸어 CI를
빨갛게 만드는 순간 "저작 우선순위 입력"이라는 이 도구의 용도가 파괴된다.

**정직 회계**(CLAUDE.md 침묵 실패 금지): 파싱 실패 라인·필드 누락·범위 밖 난이도·성취기준 대장에
없는 코드는 조용히 버리지 않고 **전부 별도 카운트로 보고**한다. "데이터 없음"(파일 부재 =
`데이터없음`)과 "0건"(파일은 있으나 문항 0 = `비어있음`)도 구분해 표기한다.

**결정론**: 난수 0·시각 의존 0·정렬 고정(단원은 총량 내림차순→코드 오름차순, 코드/라벨은 사전순).
같은 입력 파일 → 같은 바이트 출력(`--json` 산출물 포함).

**유형(17종) 축(S3-27 확장·2026-07-30)**: `Problem`↔`ProblemType` 연결(`problem_type_codes` 필드
신설·`ai_content_generation_gap_review.md` D3·`problem_bank_gap_review.md` §5-③ 유보 해제)이
착지해 더 이상 범위 밖이 아니다 — 결정론 백필(`harness/problem_type_backfill.py`)이 직접 분류 6종
2,217건 + 계보 분류 `rephrased_v0` 421건(PB-07)을 태깅해 *태깅 대상 코퍼스 7종은 전량* 채워졌다
(2026-10-09 CONT-04 실측: 스캔 전체 14,034문 중 태깅 2,638문). 나머지 코퍼스(S3-27 이후 추가분)는
아직 태깅 계약 밖이라 0커버 판정의 분모에 들어 있지 않다 — 이 계측기의 한계다.
유형×단원 매트릭스와 "17유형 중 0커버 유형 목록"을 §2.5에 낸다.
유형 카탈로그(`data/corpus/problem_type_graph_v1/problem_types.jsonl`)를 못 읽으면 이 축만
"카탈로그 미상"으로 정직하게 빠지고(exit 코드에 영향 없음) 나머지 축(성취기준·단원×난이도 등)은
그대로 낸다 — 유형 축은 관측의 *일부*일 뿐 전체 리포트의 필수 선결 조건이 아니다.

**과목 축(ARCH-28 확장·2026-08-10)**: 성취기준 대장의 `subject` 필드(2022 개정 19과목·2015 개정
13과목, 전 레코드 채움)를 투영해 과목별 커버·문항 참조 수·**0문 과목 목록**을 §1.3에 낸다 —
`Problem.subject`(코퍼스 전량 "공통"·카디널리티 1)는 과목 축으로 무효라 쓰지 않고, 고시코드
prefix 파싱도 신설하지 않는다(대장 필드가 유일한 원천 — hermetic 원칙 유지). "과목별 빠진 부분"
관측의 정본 축이며 저작 우선순위 입력이다(`subject_content_coverage_gap_review.md` §3 D1).

사용:
    python -m whymath_backend.harness.problem_bank_coverage
    python -m whymath_backend.harness.problem_bank_coverage --json out/coverage.json
    python -m whymath_backend.harness.problem_bank_coverage --revision "2015 개정"

계층 메모(CLAUDE.md 7계층): 코퍼스 JSON/JSONL을 *읽기만* 하는 빌드타임 도구다. DB·ORM·API·LLM
어느 것도 건드리지 않으며(hermetic), `schema.enums`조차 import하지 않는다 — 코퍼스 원본 문자열을
그대로 집계 키로 쓴다(스키마 enum 밖 값이 들어와도 조용히 죽지 않고 그 값 그대로 드러내기 위함).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "BAND_LABELS",
    "CorpusLoad",
    "CoverageReport",
    "ParseError",
    "ProblemRecord",
    "StandardEntry",
    "StandardsCatalog",
    "build_report",
    "difficulty_band",
    "discover_corpora",
    "load_corpus_file",
    "load_problem_types",
    "load_standards",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(다른 harness 모듈과 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
DEFAULT_STANDARDS_PATH = DEFAULT_CORPUS_ROOT / "standards_v1" / "standards.json"
# 유형(problem_type) 카탈로그(S3-27) — 17종 problem_type_id 대장. `problem_bank_coverage`는
# `schema.enums`도 import하지 않는 hermetic 원칙(모듈 docstring)을 여기서도 지킨다 — 카탈로그
# JSONL을 파싱만 하고 `problem_type_mapping` 상수는 참조하지 않는다(관측 도구가 조성 층의
# 매핑표에 의존하면 안 된다 — 매핑표가 바뀌어도 이 관측 도구는 카탈로그 파일만 보고 그대로 돈다).
DEFAULT_PROBLEM_TYPES_PATH = DEFAULT_CORPUS_ROOT / "problem_type_graph_v1" / "problem_types.jsonl"

# 문제 코퍼스 디렉터리 패턴 — `data/corpus/problem_bank*/problems.jsonl` 관례.
CORPUS_DIR_GLOB = "problem_bank*"
CORPUS_FILE_NAME = "problems.jsonl"

# 문항 코퍼스의 `curriculum_version`이 2022_REVISION이라 기본 분모는 2022 개정 성취기준이다.
DEFAULT_REVISION = "2022 개정"

# ──────────────────────────────────────────────────────────────────────────
# 난이도 밴드 — 기존 정의 재사용(신설 아님)
# ──────────────────────────────────────────────────────────────────────────
# `difficulty_overall`(1.0~5.0 실수)을 구간으로 자르는 밴드 정의는 저장소에 이미 있는 두 정본에서
# *유도*한다(자체 기준 신설 금지):
#   ① `l6/school_progress/gating.py:_DEPTH_TARGET_DIFFICULTY` — 교육과정 요구 깊이(RequiredDepth
#      awareness/procedural/conceptual/mastery)를 난이도 1.5/2.5/3.5/4.5에 앵커. 밴드 경계는 인접
#      앵커의 중점(2.0·3.0·4.0) = "가장 가까운 앵커" 분할.
#   ② `l6/gifted/gating.py:GIFTED_MIN_DIFFICULTY = 4.0` — 영재급 심화 하한. ①의 최상단 경계와
#      정확히 일치해 최상위 밴드(숙달)가 곧 영재 트랙 적격 구간이 된다.
# 이 유도 관계는 `tests/backend/harness/test_problem_bank_coverage.py`의 거버넌스 테스트가
# 실제 L6 상수를 import해 동결한다(여기서 L6를 런타임 import하지 않는 이유: 관측 도구가 응용
# 계층 게이팅에 의존하면 안 되기 때문 — 계약은 테스트로 못 박는다).
_BAND_EDGES: tuple[float, float, float] = (2.0, 3.0, 4.0)
_BAND_MIN = 1.0
_BAND_MAX = 5.0

BAND_AWARENESS = "인지 [1.0,2.0)"
BAND_PROCEDURAL = "절차 [2.0,3.0)"
BAND_CONCEPTUAL = "개념 [3.0,4.0)"
BAND_MASTERY = "숙달 [4.0,5.0]"
BAND_UNSCORED = "미평가(난이도 없음)"
BAND_OUT_OF_RANGE = "범위밖(1.0~5.0 아님)"

# 렌더·JSON 열 순서 정본(결정론 — 항상 이 순서로 낸다).
BAND_LABELS: tuple[str, ...] = (
    BAND_AWARENESS,
    BAND_PROCEDURAL,
    BAND_CONCEPTUAL,
    BAND_MASTERY,
    BAND_UNSCORED,
    BAND_OUT_OF_RANGE,
)

# 태깅이 비어 있는 문항을 매트릭스에서 지우지 않고 드러내기 위한 자리표시 키(정직 회계).
UNTAGGED_UNIT = "(단원 미태깅)"
UNSPECIFIED_FORMAT = "(형식 미지정)"
UNTAGGED_TYPE = "(유형 미태깅)"

CorpusStatus = Literal["적재됨", "비어있음", "데이터없음"]


def difficulty_band(value: float | None) -> str:
    """`difficulty_overall` → 난이도 밴드 라벨(순수·결정론).

    None은 `미평가`(값이 없는 것과 낮은 것은 다르다), [1.0,5.0] 밖은 `범위밖`으로 분리한다 —
    스키마(`Problem.difficulty_overall`, ge=1.0·le=5.0)를 벗어난 값이 코퍼스에 있으면 조용히
    가장 가까운 밴드로 뭉개지 말고 그 사실 자체를 세라는 뜻이다(정직 회계).
    """
    if value is None:
        return BAND_UNSCORED
    if value < _BAND_MIN or value > _BAND_MAX:
        return BAND_OUT_OF_RANGE
    lo, mid, hi = _BAND_EDGES
    if value < lo:
        return BAND_AWARENESS
    if value < mid:
        return BAND_PROCEDURAL
    if value < hi:
        return BAND_CONCEPTUAL
    return BAND_MASTERY


# ──────────────────────────────────────────────────────────────────────────
# 입력 모델 — 코퍼스 문항·성취기준 대장(순수 데이터·불변)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ParseError:
    """코퍼스 라인 1건의 파싱/타입 실패 — 조용히 버리지 않고 보고하기 위한 기록.

    `error_type`은 예외 타입명(CLAUDE.md "침묵 실패 금지 — 예외 타입명을 로그에 포함").
    `detail`에는 문항 본문을 담지 않는다(저작권·PII 위생 — 필드명·기대 타입 수준만).
    """

    corpus: str
    line_no: int
    error_type: str
    detail: str


@dataclass(slots=True, frozen=True)
class ProblemRecord:
    """커버리지 집계에 필요한 문항 필드만 추린 투영(불변).

    정본 스키마는 `schema/problem.py`의 `Problem`이다. 여기서는 pydantic 검증을 통과시키지
    *않는다* — 코퍼스는 스키마 밖 값(누락·범위 밖)을 담을 수 있고, 이 도구의 목적이 바로 그
    사실을 세는 것이기 때문이다(검증 게이트는 `corpus_reverify`·`corpus_audit_eval`의 몫).
    """

    corpus: str
    line_no: int
    problem_id: str | None
    unit_codes: tuple[str, ...]
    standard_codes: tuple[str, ...]
    difficulty_overall: float | None
    question_format: str | None
    problem_type_codes: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class CorpusLoad:
    """코퍼스 1종의 적재 결과 — 상태·문항·파싱 실패(불변).

    `status`는 "데이터없음"(파일 자체가 없음)과 "비어있음"(파일은 있으나 문항 0건)을 구분한다.
    둘 다 문항 수는 0이지만 의미가 전혀 다르다(전자는 관측 불가·후자는 관측된 0).
    """

    name: str
    path: Path
    status: CorpusStatus
    records: tuple[ProblemRecord, ...]
    parse_errors: tuple[ParseError, ...]


@dataclass(slots=True, frozen=True)
class StandardEntry:
    """NCIC 성취기준 1건(대장 투영·불변) — 코드는 개정별로 중복될 수 있다.

    `subject`(과목명 토큰 — 예 `10공수1`·`12확통`)는 과목 축(ARCH-28)의 유일한 원천이다.
    대장에 없는 필드는 빈 문자열로 투영하고 집계 시 `(미상)`으로 드러낸다(정직 회계).
    """

    norm_id: str
    code: str
    revision: str
    school_type: str
    domain: str
    subject: str


@dataclass(slots=True, frozen=True)
class StandardsCatalog:
    """성취기준 대장(`data/corpus/standards_v1/standards.json`) 투영(불변).

    **레코드 수 ≠ 고유 코드 수**다 — 같은 고시코드가 2015/2022 개정 양쪽에 존재하기 때문에
    (`norm_id`만 개정 접두로 다름) 커버율 분모를 레코드 수로 잡으면 이중 계산이 된다.
    분모는 항상 *하나의 개정 안의 고유 코드 집합*으로 잡는다(`codes_for`).
    """

    entries: tuple[StandardEntry, ...]

    @property
    def record_count(self) -> int:
        """대장 레코드 수(개정 중복 포함)."""
        return len(self.entries)

    @property
    def unique_codes(self) -> frozenset[str]:
        """개정을 가로지른 고유 고시코드 집합."""
        return frozenset(e.code for e in self.entries)

    @property
    def revisions(self) -> tuple[str, ...]:
        """대장에 존재하는 교육과정 개정 목록(사전순)."""
        return tuple(sorted({e.revision for e in self.entries}))

    def codes_for(self, revision: str) -> frozenset[str]:
        """해당 개정의 고유 고시코드 집합(커버율 분모)."""
        return frozenset(e.code for e in self.entries if e.revision == revision)

    def entries_for(self, revision: str) -> tuple[StandardEntry, ...]:
        """해당 개정의 대장 항목(코드 중복 제거·코드 오름차순)."""
        seen: dict[str, StandardEntry] = {}
        for entry in self.entries:
            if entry.revision == revision and entry.code not in seen:
                seen[entry.code] = entry
        return tuple(seen[code] for code in sorted(seen))


# ──────────────────────────────────────────────────────────────────────────
# 로더 — 성취기준 대장·문항 코퍼스
# ──────────────────────────────────────────────────────────────────────────
def load_standards(payload: object) -> StandardsCatalog:
    """성취기준 JSON(dict) → `StandardsCatalog`(순수).

    최상위가 dict가 아니거나 `standards` 배열이 없으면 ValueError로 즉시 실패한다 — 분모를
    모른 채 커버율을 내는 것은 관측이 아니라 날조이므로 조용한 폴백을 두지 않는다.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"성취기준 JSON 최상위가 object가 아님(type={type(payload).__name__})")
    raw = payload.get("standards")
    if not isinstance(raw, list):
        raise ValueError("성취기준 JSON에 'standards' 배열이 없음")
    entries: list[StandardEntry] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"standards[{idx}]가 object가 아님(type={type(item).__name__})")
        code = item.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError(f"standards[{idx}]에 code 문자열이 없음")
        entries.append(
            StandardEntry(
                norm_id=str(item.get("norm_id") or ""),
                code=code,
                revision=str(item.get("curriculum_revision") or ""),
                school_type=str(item.get("school_type") or ""),
                domain=str(item.get("domain") or ""),
                subject=str(item.get("subject") or ""),
            )
        )
    return StandardsCatalog(entries=tuple(entries))


def load_problem_types(payload: object) -> tuple[str, ...]:
    """유형 카탈로그(JSONL을 라인별 `json.loads`한 list) → `problem_type_id` 튜플(사전순·중복 제거).

    최상위가 list가 아니거나 원소가 object가 아니거나 `problem_type_id` 문자열이 없으면
    ValueError로 즉시 실패한다 — `load_standards`와 동일 원칙(분모를 모른 채 0커버 유형을
    내는 것은 관측이 아니라 날조). `schema.enums`·`problem_type_mapping` 어느 것도 import하지
    않는다 — 카탈로그 파일 자체가 유일한 원천이다(모듈 hermetic 원칙 유지).
    """
    if not isinstance(payload, list):
        raise ValueError(f"유형 카탈로그가 배열이 아님(type={type(payload).__name__})")
    ids: set[str] = set()
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"problem_types[{idx}]가 object가 아님(type={type(item).__name__})")
        type_id = item.get("problem_type_id")
        if not isinstance(type_id, str) or not type_id:
            raise ValueError(f"problem_types[{idx}]에 problem_type_id 문자열이 없음")
        ids.add(type_id)
    return tuple(sorted(ids))


def _str_list(value: object, field: str) -> tuple[str, ...]:
    """리스트[str] 필드 추출 — None/부재는 빈 튜플, 타입 위반은 TypeError(라인 단위 보고용)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"{field}가 배열이 아님(type={type(value).__name__})")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field} 원소가 문자열이 아님(type={type(item).__name__})")
        out.append(item)
    return tuple(out)


def _opt_float(value: object, field: str) -> float | None:
    """실수 필드 추출 — None/부재는 None, 비수치는 TypeError(bool은 int 하위형이라 명시 배제)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field}가 수치가 아님(type={type(value).__name__})")
    return float(value)


def _opt_str(value: object, field: str) -> str | None:
    """문자열 필드 추출 — None/부재는 None, 타입 위반은 TypeError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}가 문자열이 아님(type={type(value).__name__})")
    return value


def parse_problem_line(raw: str, *, corpus: str, line_no: int) -> ProblemRecord:
    """JSONL 한 줄 → `ProblemRecord`(순수). 실패는 예외로 올려 호출자가 카운트한다."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise TypeError(f"레코드가 object가 아님(type={type(obj).__name__})")
    return ProblemRecord(
        corpus=corpus,
        line_no=line_no,
        problem_id=_opt_str(obj.get("problem_id"), "problem_id"),
        unit_codes=_str_list(obj.get("unit_codes"), "unit_codes"),
        standard_codes=_str_list(
            obj.get("achievement_standard_codes"), "achievement_standard_codes"
        ),
        difficulty_overall=_opt_float(obj.get("difficulty_overall"), "difficulty_overall"),
        question_format=_opt_str(obj.get("question_format"), "question_format"),
        problem_type_codes=_str_list(obj.get("problem_type_codes"), "problem_type_codes"),
    )


def load_corpus_file(path: Path, *, name: str) -> CorpusLoad:
    """`problems.jsonl` 1개 → `CorpusLoad`(파일 부재도 예외 없이 상태로 표현).

    라인 파싱 실패는 그 라인만 `parse_errors`에 적재하고 나머지 라인 집계는 계속한다 — 관측
    리포트라 부분 실패로 전체를 버리지 않되, 버린 라인 수를 반드시 표면화한다(정직 회계).
    """
    if not path.is_file():
        return CorpusLoad(name=name, path=path, status="데이터없음", records=(), parse_errors=())
    records: list[ProblemRecord] = []
    errors: list[ParseError] = []
    text = path.read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            records.append(parse_problem_line(stripped, corpus=name, line_no=line_no))
        except Exception as exc:  # noqa: BLE001 — 라인 단위 격리·예외 타입명을 그대로 보고
            errors.append(
                ParseError(
                    corpus=name,
                    line_no=line_no,
                    error_type=type(exc).__name__,
                    detail=str(exc)[:200],
                )
            )
    status: CorpusStatus = "적재됨" if records else "비어있음"
    return CorpusLoad(
        name=name,
        path=path,
        status=status,
        records=tuple(records),
        parse_errors=tuple(errors),
    )


def discover_corpora(corpus_root: Path) -> tuple[Path, ...]:
    """`data/corpus/problem_bank*/problems.jsonl`을 이름 오름차순으로 탐색(결정론)."""
    if not corpus_root.is_dir():
        return ()
    found = [
        child / CORPUS_FILE_NAME for child in corpus_root.glob(CORPUS_DIR_GLOB) if child.is_dir()
    ]
    return tuple(sorted(found, key=lambda p: p.parent.name))


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 커버리지 리포트(순수 코어)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class CoverageReport:
    """커버리지 관측 결과 전량(불변·렌더/직렬화의 단일 입력).

    모든 dict는 렌더 시점에 정렬해 쓰므로 삽입 순서에 의존하지 않는다(결정론).
    """

    revision: str
    corpora: tuple[CorpusLoad, ...]
    total_problems: int
    parse_errors: tuple[ParseError, ...]
    # 성취기준 축
    standards_record_count: int
    standards_unique_code_count: int
    standards_by_revision: dict[str, int]
    target_codes_total: int
    covered_codes: tuple[str, ...]
    zero_coverage_codes: tuple[str, ...]
    problems_per_covered_code: dict[str, int]
    coverage_by_school_type: dict[str, tuple[int, int]]
    coverage_by_domain: dict[str, tuple[int, int]]
    # 과목 축(ARCH-28) — 분모=대장 subject별 고유 코드, 참조=커버 코드의 문항 수 합(중복 가산).
    coverage_by_subject: dict[str, tuple[int, int]]
    problems_per_subject: dict[str, int]
    other_revision_only_codes: dict[str, int]
    unknown_standard_codes: dict[str, int]
    # 단원 × 난이도 밴드 축
    unit_band_matrix: dict[str, dict[str, int]]
    band_totals: dict[str, int]
    # 분해 축
    per_corpus_bands: dict[str, dict[str, int]]
    per_corpus_formats: dict[str, dict[str, int]]
    format_totals: dict[str, int]
    # 유형(problem_type) × 단원 축 (S3-27)
    problem_types_catalog: tuple[str, ...]  # 카탈로그 로드 실패/미지정 시 빈 튜플(정직 회계).
    type_unit_matrix: dict[str, dict[str, int]]
    # 정직 회계
    problems_without_standard_codes: int
    problems_without_unit_codes: int
    problems_without_difficulty: int
    problems_without_question_format: int
    problems_without_problem_type: int

    @property
    def covered_code_count(self) -> int:
        return len(self.covered_codes)

    @property
    def coverage_rate(self) -> float | None:
        """분모(해당 개정 고유 코드 수)가 0이면 None — 가짜 0/1 금지."""
        if self.target_codes_total == 0:
            return None
        return self.covered_code_count / self.target_codes_total

    @property
    def zero_problem_subjects(self) -> tuple[str, ...]:
        """대장에 성취기준이 있는데(분모>0) 커버 코드 0인 과목 — "과목별 빠진 부분"의 발화 계측기.

        커버 코드 0 ⟺ 문항 참조 0(`problems_per_subject`에 키 부재)이므로 "그 과목 문항이 대상
        개정 기준 1건도 없다"와 동치다. subject 결측(`(미상)`) 키도 숨기지 않는다(정직 회계).
        """
        return tuple(
            sorted(s for s, (cov, tot) in self.coverage_by_subject.items() if tot > 0 and cov == 0)
        )

    @property
    def unit_totals(self) -> dict[str, int]:
        return {unit: sum(bands.values()) for unit, bands in self.unit_band_matrix.items()}

    def sorted_units(self) -> tuple[str, ...]:
        """단원 정렬 — 총량 내림차순 → 코드 오름차순(동률 결정론)."""
        totals = self.unit_totals
        return tuple(sorted(totals, key=lambda u: (-totals[u], u)))

    @property
    def type_totals(self) -> dict[str, int]:
        """유형별 총 문항 수(행 합계) — 다중 단원 문항은 중복 가산 가능(unit_totals와 동일 관례)."""
        return {ptype: sum(units.values()) for ptype, units in self.type_unit_matrix.items()}

    @property
    def zero_coverage_types(self) -> tuple[str, ...]:
        """카탈로그 중 문항이 1건도 없는 `problem_type_id`(§4-① 트리거의 발화 계측기).

        카탈로그가 비어 있으면(로드 실패/미지정) 빈 튜플 — "0커버"와 "카탈로그 모름"을
        혼동하지 않는다(정직 회계).
        """
        if not self.problem_types_catalog:
            return ()
        totals = self.type_totals
        return tuple(sorted(t for t in self.problem_types_catalog if totals.get(t, 0) == 0))

    def sorted_problem_types(self) -> tuple[str, ...]:
        """유형 행 순서 — 카탈로그(사전순 튜플) 전량 + 카탈로그 밖 유형(관측됐으나 대장에 없는
        값·스키마 오류 등)을 뒤에 사전순으로 덧붙인다. 카탈로그가 없으면(로드 실패·미지정)
        관측된 유형만 사전순으로 낸다(0커버 유형은 이 경우 정의 불가 — `zero_coverage_types` 참고).
        """
        totals = self.type_totals
        if self.problem_types_catalog:
            catalog_set = set(self.problem_types_catalog)
            extra = sorted(t for t in totals if t not in catalog_set)
            return tuple(self.problem_types_catalog) + tuple(extra)
        return tuple(sorted(totals))


def build_report(
    loads: tuple[CorpusLoad, ...],
    catalog: StandardsCatalog,
    *,
    revision: str,
    problem_types: tuple[str, ...] = (),
) -> CoverageReport:
    """코퍼스 적재 결과 + 성취기준 대장 → `CoverageReport`(순수·부작용 0).

    `problem_types`(S3-27)는 선택 인자다 — 미지정(기본 빈 튜플)이면 유형×단원 축은 관측된
    유형만으로 채워지고 `zero_coverage_types`는 항상 빈 튜플이다(카탈로그를 모르면 "0커버"를
    단정할 수 없다 — 정직 회계). 기존 호출자(카탈로그 없이 `build_report(loads, catalog,
    revision=...)`만 쓰는 코드)는 그대로 동작한다(하위호환).
    """
    target_codes = catalog.codes_for(revision)
    all_codes = catalog.unique_codes

    per_code: Counter[str] = Counter()
    other_revision: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    unit_matrix: dict[str, Counter[str]] = {}
    band_totals: Counter[str] = Counter()
    per_corpus_bands: dict[str, Counter[str]] = {}
    per_corpus_formats: dict[str, Counter[str]] = {}
    format_totals: Counter[str] = Counter()
    type_unit_matrix: dict[str, Counter[str]] = {}
    no_std = no_unit = no_diff = no_format = no_type = 0
    total = 0

    for load in loads:
        per_corpus_bands.setdefault(load.name, Counter())
        per_corpus_formats.setdefault(load.name, Counter())
        for rec in load.records:
            total += 1
            band = difficulty_band(rec.difficulty_overall)
            band_totals[band] += 1
            per_corpus_bands[load.name][band] += 1
            fmt = rec.question_format or UNSPECIFIED_FORMAT
            per_corpus_formats[load.name][fmt] += 1
            format_totals[fmt] += 1
            if rec.difficulty_overall is None:
                no_diff += 1
            if rec.question_format is None:
                no_format += 1
            # 단원 × 밴드 — 한 문항이 여러 단원을 가지면 각 단원에 1씩 센다(문항 합 ≠ 총 문항 수).
            units = rec.unit_codes or (UNTAGGED_UNIT,)
            if not rec.unit_codes:
                no_unit += 1
            for unit in units:
                unit_matrix.setdefault(unit, Counter())[band] += 1
            # 유형 × 단원(S3-27) — 유형 축도 단원 축과 같은 관례(다중 단원=중복 가산).
            if not rec.problem_type_codes:
                no_type += 1
            for ptype in rec.problem_type_codes:
                for unit in units:
                    type_unit_matrix.setdefault(ptype, Counter())[unit] += 1
            # 성취기준 — 대장에 있는지, 있다면 대상 개정인지 3분류(미지 코드를 조용히 버리지 않음).
            if not rec.standard_codes:
                no_std += 1
            for code in rec.standard_codes:
                if code in target_codes:
                    per_code[code] += 1
                elif code in all_codes:
                    other_revision[code] += 1
                else:
                    unknown[code] += 1

    covered = tuple(sorted(per_code))
    zero = tuple(sorted(target_codes - set(covered)))

    # 학교급·영역·과목별 커버(분모=해당 개정 고유 코드, 분자=그중 커버된 코드).
    by_school: dict[str, list[int]] = {}
    by_domain: dict[str, list[int]] = {}
    by_subject: dict[str, list[int]] = {}
    covered_set = set(covered)
    subject_of: dict[str, str] = {}
    for entry in catalog.entries_for(revision):
        subject_of[entry.code] = entry.subject or "(미상)"
        for bucket, key in (
            (by_school, entry.school_type),
            (by_domain, entry.domain),
            (by_subject, entry.subject),
        ):
            slot = bucket.setdefault(key or "(미상)", [0, 0])
            slot[1] += 1
            if entry.code in covered_set:
                slot[0] += 1

    # 과목별 문항 참조 수 — 커버 코드의 문항 수를 과목으로 합산. 한 문항이 같은 과목 코드를
    # 여러 개 가지면 코드마다 1씩 세므로 과목 합계 ≠ 총 문항 수(unit_totals와 동일 관례).
    per_subject: Counter[str] = Counter()
    for code, count in per_code.items():
        per_subject[subject_of[code]] += count

    return CoverageReport(
        revision=revision,
        corpora=loads,
        total_problems=total,
        parse_errors=tuple(err for load in loads for err in load.parse_errors),
        standards_record_count=catalog.record_count,
        standards_unique_code_count=len(all_codes),
        standards_by_revision={rev: len(catalog.codes_for(rev)) for rev in catalog.revisions},
        target_codes_total=len(target_codes),
        covered_codes=covered,
        zero_coverage_codes=zero,
        problems_per_covered_code=dict(per_code),
        coverage_by_school_type={k: (v[0], v[1]) for k, v in by_school.items()},
        coverage_by_domain={k: (v[0], v[1]) for k, v in by_domain.items()},
        coverage_by_subject={k: (v[0], v[1]) for k, v in by_subject.items()},
        problems_per_subject=dict(per_subject),
        other_revision_only_codes=dict(other_revision),
        unknown_standard_codes=dict(unknown),
        unit_band_matrix={unit: dict(bands) for unit, bands in unit_matrix.items()},
        band_totals=dict(band_totals),
        per_corpus_bands={name: dict(bands) for name, bands in per_corpus_bands.items()},
        per_corpus_formats={name: dict(fmts) for name, fmts in per_corpus_formats.items()},
        format_totals=dict(format_totals),
        problem_types_catalog=tuple(problem_types),
        type_unit_matrix={ptype: dict(units) for ptype, units in type_unit_matrix.items()},
        problems_without_standard_codes=no_std,
        problems_without_unit_codes=no_unit,
        problems_without_difficulty=no_diff,
        problems_without_question_format=no_format,
        problems_without_problem_type=no_type,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _pct(numerator: int, denominator: int) -> str:
    """비율 렌더 — 분모 0은 '데이터없음'(0.0%로 위장 금지)."""
    if denominator == 0:
        return "데이터없음"
    return f"{numerator / denominator * 100:.1f}%"


def _sorted_counts(counts: dict[str, int]) -> list[tuple[str, int]]:
    """카운트 정렬 — 값 내림차순 → 키 오름차순(결정론)."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def render_report(report: CoverageReport, *, max_zero_codes: int = 40) -> str:
    """커버리지 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음).

    0커버 코드 목록은 `max_zero_codes`개까지만 본문에 싣고 나머지는 건수로 요약한다(전량은
    `--json` 산출물에 있다). 잘렸다는 사실 자체를 문장으로 남긴다 — 조용한 절단 금지.
    """
    lines: list[str] = [
        "# 문제은행 커버리지 관측 리포트 (D4)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(커버율 임계로 실패시키지 않는다).",
        "> S4-01 초·중 확장의 저작 우선순위 입력. 유형(problem_type) × 단원 축은 §2.5(S3-27).",
        "",
        "## 0. 입력 요약",
        "",
        f"- 문항 총계: **{report.total_problems}**문 (코퍼스 {len(report.corpora)}종)",
        f"- 성취기준 대장: 레코드 **{report.standards_record_count}** · "
        f"고유 코드 **{report.standards_unique_code_count}** "
        f"(같은 고시코드가 개정별로 중복 등재 — 분모는 개정 내 고유 코드)",
    ]
    for rev, count in sorted(report.standards_by_revision.items()):
        mark = " ← 이번 분모" if rev == report.revision else ""
        lines.append(f"  - {rev}: 고유 코드 {count}{mark}")
    lines += ["", "| 코퍼스 | 상태 | 문항 | 파싱 실패 |", "|---|---|---:|---:|"]
    for load in report.corpora:
        lines.append(
            f"| `{load.name}` | {load.status} | {len(load.records)} | {len(load.parse_errors)} |"
        )

    lines += [
        "",
        "## 1. 성취기준 커버리지",
        "",
        f"- 대상 개정: **{report.revision}** · 분모(고유 코드) **{report.target_codes_total}**",
        f"- 커버된 코드: **{report.covered_code_count}** "
        f"({_pct(report.covered_code_count, report.target_codes_total)})",
        f"- 0커버 코드: **{len(report.zero_coverage_codes)}**",
        "",
        "### 1.1 학교급별 커버율",
        "",
        "| 학교급 | 커버 | 분모 | 커버율 |",
        "|---|---:|---:|---:|",
    ]
    for school, (cov, tot) in sorted(
        report.coverage_by_school_type.items(), key=lambda kv: (-kv[1][1], kv[0])
    ):
        lines.append(f"| {school} | {cov} | {tot} | {_pct(cov, tot)} |")

    lines += [
        "",
        "### 1.2 영역별 커버율",
        "",
        "| 영역 | 커버 | 분모 | 커버율 |",
        "|---|---:|---:|---:|",
    ]
    for domain, (cov, tot) in sorted(
        report.coverage_by_domain.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0])
    ):
        lines.append(f"| {domain} | {cov} | {tot} | {_pct(cov, tot)} |")

    lines += [
        "",
        "### 1.3 과목별 커버리지 (ARCH-28)",
        "",
        "> 과목은 성취기준 대장의 `subject` 필드다(`Problem.subject`·코드 prefix 파싱 아님).",
        "> 문항 참조는 커버 코드의 문항 수 합 — 한 문항이 같은 과목 코드를 여러 개 가지면",
        "> 코드마다 1씩 센다(§2 단원 축과 동일한 중복 가산 관례).",
        ">",
        "> **범위 한정(정직 회계)**: 이 축의 분모는 `--standards`가 가리키는 대장 하나뿐이다.",
        "> 기본 경로는 K-12 대장(`standards_v1`)이라 **대학 과목은 분모에 아예 없다** — 아래",
        '> "0문 과목"은 *그 대장 안에서의* 0문이지 전 학교급 판정이 아니다. 대학 축(32과목·',
        "> 409코드)의 문항 커버는 이 도구가 관측하지 않는다(미관측이지 0건이 아니다).",
        "",
        "| 과목 | 커버 | 분모 | 커버율 | 문항 참조 |",
        "|---|---:|---:|---:|---:|",
    ]
    for subject, (cov, tot) in sorted(
        report.coverage_by_subject.items(), key=lambda kv: (-kv[1][1], kv[0])
    ):
        refs = report.problems_per_subject.get(subject, 0)
        lines.append(f"| {subject} | {cov} | {tot} | {_pct(cov, tot)} | {refs} |")
    if report.zero_problem_subjects:
        lines += [
            "",
            f"- **0문 과목 {len(report.zero_problem_subjects)}종**: "
            + " ".join(f"`{s}`" for s in report.zero_problem_subjects)
            + " — 대장에 성취기준이 있는데 대상 개정 기준 문항이 1건도 없다.",
        ]
    else:
        lines += ["", "- 0문 과목: 없음(대장 전 과목이 1문 이상 참조됨)."]

    lines += ["", "### 1.4 커버된 코드 상위 (문항 수)", "", "| 성취기준 | 문항 |", "|---|---:|"]
    for code, count in _sorted_counts(report.problems_per_covered_code)[:20]:
        lines.append(f"| `{code}` | {count} |")

    shown = report.zero_coverage_codes[:max_zero_codes]
    remainder = len(report.zero_coverage_codes) - len(shown)
    lines += ["", "### 1.5 0커버 코드 목록", ""]
    if not report.zero_coverage_codes:
        lines.append("- 없음(대상 개정 전 코드가 1문 이상 커버됨).")
    else:
        lines.append("- " + " ".join(f"`{c}`" for c in shown))
        if remainder > 0:
            lines.append(
                f"- …외 **{remainder}**건(전량은 `--json` 산출물의 `zero_coverage_codes`)."
            )

    lines += [
        "",
        "## 2. 단원(unit_code) × 난이도 밴드 분포",
        "",
        "> 밴드 경계는 L6 기존 정본에서 유도 — `_DEPTH_TARGET_DIFFICULTY`(RequiredDepth 앵커 "
        "1.5/2.5/3.5/4.5)의 중점 2.0·3.0·4.0, 최상단 4.0은 `GIFTED_MIN_DIFFICULTY`와 일치.",
        "> 한 문항이 여러 단원을 가지면 각 단원에 1씩 세므로 행 합계는 총 문항 수와 다를 수 있다.",
        "",
        "| 단원 | " + " | ".join(BAND_LABELS) + " | 합계 |",
        "|---" * (len(BAND_LABELS) + 2) + "|",
    ]
    totals = report.unit_totals
    for unit in report.sorted_units():
        row = report.unit_band_matrix[unit]
        cells = " | ".join(str(row.get(band, 0)) for band in BAND_LABELS)
        lines.append(f"| `{unit}` | {cells} | {totals[unit]} |")
    band_row = " | ".join(str(report.band_totals.get(band, 0)) for band in BAND_LABELS)
    lines.append(f"| **문항 기준 합계** | {band_row} | {report.total_problems} |")

    # ── 2.5 유형(problem_type) × 단원 분포(S3-27) ──
    lines += [
        "",
        "## 2.5 유형(problem_type) × 단원 분포",
        "",
        "> `problem_type_codes`(S3-27 백필) 기반 — 유보 해제 근거는 `ai_content_generation_gap_"
        "review.md` D3·`problem_bank_gap_review.md` §5-③ 편집자 부기. 한 문항이 여러 단원을 "
        "가지면 각 단원에 1씩 세므로 행 합계는 총 태깅 문항 수와 다를 수 있다(§2 관례 동일).",
    ]
    if not report.problem_types_catalog:
        lines.append("- 유형 카탈로그 미상(로드 실패 또는 미지정) — 이 축은 관측 불가로 표시.")
    type_units = sorted({unit for units in report.type_unit_matrix.values() for unit in units})
    if not type_units:
        lines.append("- 유형 태깅된 문항 없음(비어있음).")
    else:
        lines += [
            "",
            "| 유형(problem_type_id) | " + " | ".join(f"`{u}`" for u in type_units) + " | 합계 |",
            "|---" * (len(type_units) + 2) + "|",
        ]
        totals = report.type_totals
        for ptype in report.sorted_problem_types():
            row = report.type_unit_matrix.get(ptype, {})
            cells = " | ".join(str(row.get(u, 0)) for u in type_units)
            lines.append(f"| `{ptype}` | {cells} | {totals.get(ptype, 0)} |")

    lines += ["", "### 2.5.1 0커버 유형 목록", ""]
    if not report.problem_types_catalog:
        lines.append("- 카탈로그 미상 — 0커버 판정 불가(정직 회계).")
    elif not report.zero_coverage_types:
        lines.append("- 없음(카탈로그 전 유형이 1문 이상 태깅됨).")
    else:
        lines.append("- " + " ".join(f"`{t}`" for t in report.zero_coverage_types))
        lines.append(
            f"- 이 목록이 §4-① 트리거의 발화 계측기다(`ai_content_generation_gap_review.md` "
            f"D3) — **{len(report.zero_coverage_types)}**/{len(report.problem_types_catalog)}종 "
            "미커버."
        )

    lines += ["", "## 3. 코퍼스별 분해", "", "| 코퍼스 | " + " | ".join(BAND_LABELS) + " |"]
    lines.append("|---" * (len(BAND_LABELS) + 1) + "|")
    for load in report.corpora:
        row = report.per_corpus_bands.get(load.name, {})
        cells = " | ".join(str(row.get(band, 0)) for band in BAND_LABELS)
        lines.append(f"| `{load.name}` | {cells} |")

    formats = [name for name, _ in _sorted_counts(report.format_totals)]
    lines += [
        "",
        "## 4. 질문형식별 분해",
        "",
        "| 코퍼스 | " + " | ".join(formats or ["(없음)"]) + " |",
    ]
    lines.append("|---" * (len(formats or ["x"]) + 1) + "|")
    for load in report.corpora:
        row = report.per_corpus_formats.get(load.name, {})
        cells = " | ".join(str(row.get(fmt, 0)) for fmt in formats) if formats else "0"
        lines.append(f"| `{load.name}` | {cells} |")
    if formats:
        total_cells = " | ".join(str(report.format_totals[fmt]) for fmt in formats)
        lines.append(f"| **합계** | {total_cells} |")

    lines += [
        "",
        "## 5. 정직 회계 (누락·미지 값)",
        "",
        "> 조용히 버리지 않는다 — 아래가 모두 0이어야 위 수치를 액면 그대로 읽을 수 있다.",
        "",
        "| 항목 | 건수 |",
        "|---|---:|",
        f"| 파싱 실패 라인 | {len(report.parse_errors)} |",
        f"| 성취기준 코드 없는 문항 | {report.problems_without_standard_codes} |",
        f"| 단원 코드 없는 문항 | {report.problems_without_unit_codes} |",
        f"| 난이도 없는 문항 | {report.problems_without_difficulty} |",
        f"| 질문형식 없는 문항 | {report.problems_without_question_format} |",
        f"| 유형(problem_type) 없는 문항 | {report.problems_without_problem_type} |",
        f"| 대장에 없는 성취기준 코드(종) | {len(report.unknown_standard_codes)} |",
        f"| 다른 개정에만 있는 코드(종) | {len(report.other_revision_only_codes)} |",
    ]
    if report.unknown_standard_codes:
        lines += ["", "### 5.1 대장에 없는 성취기준 코드", ""]
        for code, count in _sorted_counts(report.unknown_standard_codes):
            lines.append(f"- `{code}` — {count}문")
    if report.other_revision_only_codes:
        lines += ["", f"### 5.2 {report.revision} 밖(다른 개정)에만 있는 코드", ""]
        for code, count in _sorted_counts(report.other_revision_only_codes):
            lines.append(f"- `{code}` — {count}문")
    if report.parse_errors:
        lines += ["", "### 5.3 파싱 실패 라인", ""]
        for err in report.parse_errors:
            lines.append(f"- `{err.corpus}` line {err.line_no}: {err.error_type} — {err.detail}")
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: CoverageReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "revision": report.revision,
        "total_problems": report.total_problems,
        "corpora": [
            {
                "name": load.name,
                "status": load.status,
                "problems": len(load.records),
                "parse_errors": len(load.parse_errors),
            }
            for load in report.corpora
        ],
        "standards": {
            "record_count": report.standards_record_count,
            "unique_code_count": report.standards_unique_code_count,
            "unique_codes_by_revision": report.standards_by_revision,
            "target_revision": report.revision,
            "target_codes_total": report.target_codes_total,
            "covered_code_count": report.covered_code_count,
            "coverage_rate": report.coverage_rate,
            "zero_coverage_code_count": len(report.zero_coverage_codes),
        },
        "covered_codes": list(report.covered_codes),
        "zero_coverage_codes": list(report.zero_coverage_codes),
        "problems_per_covered_code": report.problems_per_covered_code,
        "coverage_by_school_type": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_school_type.items()
        },
        "coverage_by_domain": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_domain.items()
        },
        "coverage_by_subject": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_subject.items()
        },
        "problems_per_subject": report.problems_per_subject,
        "zero_problem_subjects": list(report.zero_problem_subjects),
        "band_labels": list(BAND_LABELS),
        "unit_band_matrix": report.unit_band_matrix,
        "band_totals": report.band_totals,
        "per_corpus_bands": report.per_corpus_bands,
        "per_corpus_formats": report.per_corpus_formats,
        "format_totals": report.format_totals,
        "problem_types": {
            "catalog": list(report.problem_types_catalog),
            "catalog_count": len(report.problem_types_catalog),
            "type_unit_matrix": report.type_unit_matrix,
            "type_totals": report.type_totals,
            "zero_coverage_types": list(report.zero_coverage_types),
            "zero_coverage_type_count": len(report.zero_coverage_types),
        },
        "honest_accounting": {
            "parse_error_lines": len(report.parse_errors),
            "parse_errors": [
                {
                    "corpus": e.corpus,
                    "line_no": e.line_no,
                    "error_type": e.error_type,
                    "detail": e.detail,
                }
                for e in report.parse_errors
            ],
            "problems_without_standard_codes": report.problems_without_standard_codes,
            "problems_without_unit_codes": report.problems_without_unit_codes,
            "problems_without_difficulty": report.problems_without_difficulty,
            "problems_without_question_format": report.problems_without_question_format,
            "problems_without_problem_type": report.problems_without_problem_type,
            "unknown_standard_codes": report.unknown_standard_codes,
            "other_revision_only_codes": report.other_revision_only_codes,
        },
    }


def dump_json(report: CoverageReport) -> str:
    """JSON 직렬화 — 키 정렬·들여쓰기 고정으로 같은 입력에 같은 바이트를 보장(결정론)."""
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — 경로 해석·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_loads(
    corpus_root: Path, names: list[str] | None
) -> tuple[tuple[CorpusLoad, ...], list[str]]:
    """코퍼스 경로 해석 → 적재. 명시 지정한 코퍼스가 없으면 '데이터없음' 상태 + 오류 메시지."""
    problems: list[str] = []
    if names:
        paths = tuple(corpus_root / name / CORPUS_FILE_NAME for name in names)
    else:
        paths = discover_corpora(corpus_root)
        if not paths:
            problems.append(
                f"코퍼스를 찾지 못함: {corpus_root}/{CORPUS_DIR_GLOB}/{CORPUS_FILE_NAME}"
            )
    loads = tuple(load_corpus_file(p, name=p.parent.name) for p in paths)
    for load in loads:
        if load.status == "데이터없음":
            problems.append(f"코퍼스 파일 없음: {load.path}")
    return loads, problems


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 커버리지 관측 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    커버율이 0%여도 exit 0이다 — 게이트가 아니라 관측이기 때문(`corpus_audit_eval`과의 차이).
    exit 2는 *관측 자체가 불가능한* 입력 오류(성취기준 대장 부재·파싱 불가, 지정 코퍼스 부재)에만
    쓴다. 라인 단위 파싱 실패는 리포트에 카운트로 실리고 종료 코드에 영향을 주지 않는다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_bank_coverage",
        description=(
            "문제은행 커버리지 관측 리포트(D4) — 성취기준 커버율·0커버 목록, unit_code×난이도 "
            "밴드 매트릭스, 코퍼스별·질문형식별 분해. 결정론·게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=DEFAULT_CORPUS_ROOT,
        help=f"코퍼스 루트 디렉터리(기본 {DEFAULT_CORPUS_ROOT}).",
    )
    parser.add_argument(
        "--corpus",
        action="append",
        default=None,
        help="집계할 코퍼스 디렉터리명(반복 지정 가능·기본은 problem_bank* 전량 탐색).",
    )
    parser.add_argument(
        "--standards",
        type=Path,
        default=DEFAULT_STANDARDS_PATH,
        help=f"NCIC 성취기준 JSON 경로(기본 {DEFAULT_STANDARDS_PATH}).",
    )
    parser.add_argument(
        "--revision",
        type=str,
        default=DEFAULT_REVISION,
        help=f"커버율 분모로 쓸 교육과정 개정(기본 '{DEFAULT_REVISION}').",
    )
    parser.add_argument(
        "--max-zero-codes",
        type=int,
        default=40,
        help="본문에 나열할 0커버 코드 최대 개수(기본 40·전량은 --json).",
    )
    parser.add_argument(
        "--problem-types",
        type=Path,
        default=DEFAULT_PROBLEM_TYPES_PATH,
        help=f"유형(problem_type) 카탈로그 JSONL 경로(기본 {DEFAULT_PROBLEM_TYPES_PATH}).",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=None,
        help="JSON 산출물 경로(선택·미지정이면 stdout 마크다운만).",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.standards.read_text(encoding="utf-8"))
        catalog = load_standards(payload)
    except Exception as exc:  # noqa: BLE001 — 입력 오류는 타입명과 함께 보고하고 exit 2
        print(f"입력 오류 — 성취기준 대장 적재 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    if args.revision not in catalog.revisions:
        print(
            f"입력 오류 — 대장에 없는 개정 '{args.revision}'"
            f"(가능: {', '.join(catalog.revisions) or '없음'})",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR

    # 유형 카탈로그(S3-27)는 *보조 축*이다 — 못 읽어도 exit 2로 전체 리포트를 막지 않는다
    # (성취기준 대장과 달리 유형 축은 관측의 일부일 뿐 필수 선결 조건이 아니다 — 모듈 docstring).
    # 실패는 조용히 넘기지 않고 stderr에 예외 타입명과 함께 경고한다(침묵 실패 금지).
    problem_types: tuple[str, ...] = ()
    try:
        raw_lines = args.problem_types.read_text(encoding="utf-8").splitlines()
        parsed = [json.loads(line) for line in raw_lines if line.strip()]
        problem_types = load_problem_types(parsed)
    except Exception as exc:  # noqa: BLE001 — 보조 축 실패는 경고만(예외 타입명 포함)하고 계속
        print(
            f"경고 — 유형 카탈로그 적재 실패({type(exc).__name__}): {exc} "
            "— 유형×단원 축은 '카탈로그 미상'으로 표시됩니다.",
            file=sys.stderr,
        )

    loads, problems = _resolve_loads(args.corpus_root, args.corpus)
    report = build_report(loads, catalog, revision=args.revision, problem_types=problem_types)
    print(render_report(report, max_zero_codes=args.max_zero_codes))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    if problems:
        for msg in problems:
            print(f"입력 오류 — {msg}", file=sys.stderr)
        return _EXIT_INPUT_ERROR
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
