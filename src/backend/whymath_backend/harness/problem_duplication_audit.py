"""문항 코퍼스 중복 감사 — T1(슬러그 충돌)·T2(실중복 발문)·T3(verify.conditions 비-기준) 3축.

배경 — QUAL-01(장기 미병합 브랜치 8ceaf5의 원 QUAL-01 재작성)
------------------------------------------------------------
장기 미병합 브랜치 `claude/whymath-data-platform-design-8ceaf5`(2026-08-03)의 원 설계 문서가
"문항 수준 중복 감사"를 T1/T2/T3 3계층으로 설계했다. 그 브랜치는 트렁크에 랜딩한 적이 없고
(`docs/architecture/data_platform_module_gap_review.md` §4 "이 감사가 하지 않는 것" — OPS-22가
이 축을 명시적으로 범위 밖에 남겼다: "그 갭이 현재도 유효한지는 별도 실측이 필요"), 원 문서의
수치(슬러그 충돌 392건)는 2026-08-03 시점 과거 스냅샷이라 재검증 없이 신뢰할 수 없었다. 이
모듈이 그 재검증이다.

T1 — 코퍼스 간 슬러그 충돌
---------------------------
전 코퍼스(`problem_bank*`) 쌍별 `slug` 교집합. 원 설계 문서가 보고한 392건
(`generated_v0 ∩ rephrased_v0`)은 이 재측정(2026-08-10)에서 **0건**으로 나온다 — 해소 원인은
조사하지 않았다(슬러그 네임스페이싱 변경 등으로 추정, 재조사는 이 태스크 범위 밖). "0건"과
"검사 안 함"을 구분하려고 스캔한 코퍼스 쌍 수 자체를 항상 리포트에 명시한다(정직 회계).

T2 — 실중복(정규화된 question_text 완전 일치)
-----------------------------------------------
"실중복" 최소 기준(코드: `find_duplicate_pairs`) — 아래 3개를 **전부** 만족해야 한다:
  (a) 서로 다른 코퍼스 파일(은행) 소속
  (b) `question_text`를 NFC 정규화 + 공백 연속 축약한 후 바이트 단위 완전 일치
  (c) 코퍼스가 스스로 선언한 `relations[].parent_slug` 계보 그래프(S4-14 스켈레톤 계보·S4-18
      identity/재서술 계보가 쓰는 것과 같은 필드)에서 같은 연결요소(BFS 폐포)에 속하는 "정당한
      형제"가 아님

이 기준으로 전 코퍼스(2026-08 기준 7종 2,647문)를 스캔하면 **9쌍**이 나왔다 — 원 문서가 지목한 1쌍
(`wm-quad-eq-larger-root` ↔ `wm-skel-92cd1ba2bbf5`, 여전히 재현됨)뿐 아니라, 이번 실측에서
**새로 발견한 8쌍**(단답형/객관식 스켈레톤 트윈이 "재서술이 발문을 바꾸지 않은" 현상과 교차
매칭된 경우 — `render_report` §2.2 참고)이 있다. 후자는 계보 필드가 "형식 트윈" 관계를 애초에
포착하지 않는다는 코퍼스 설계상의 정직한 공백이지, 배제 로직의 결함이 아니다 — 슬러그 문자열
패턴 매칭 같은 새 휴리스틱을 발명해 조용히 덮지 않는다(CLAUDE.md "환경 사실의 추론 등재 금지"·
"정직 회계" 원칙 — 계보 필드가 없으면 없다고 드러낸다).

T3 — verify.conditions 서명 동일은 판정 기준이 아니다(계산하지 않음)
-----------------------------------------------------------------
원 설계 문서의 핵심 발견: `verify.conditions` 문자열 동일은 **오탐 유발** 신호라 중복 판정에
쓰면 안 된다. 실측 반례 `wm-skel-f50f96b5a691`("이차방정식 x^2 + 2x - 48 = 0 의 두 근 중 큰
근은?")과 `wm-calc-ext-8c193941df77`("삼차함수 f(x) = x^3 + 3x^2 - 144x 가 극소가 되는 x의 값을
구하시오.")는 `verify.conditions`가 둘 다 `"x**2 + 2*x - 48 = 0"`으로 바이트 단위 동일하다
(후자의 도함수 f'(x)=3x²+6x-144=3(x²+2x-48)이 그 이차식이기 때문) — 그러나 교수학적으로는
완전히 다른 문항이다. 이 모듈이 그대로 재확인했다(`problem_bank_generated_v0`·
`problem_bank_rephrased_v0` 양쪽에 두 slug가 실재). 이 축은 **코드로 계산하지 않는다** —
`render_report` §3의 문서화가 유일한 산출물이다. `verify`/`answer`/`choices` 필드는 이 모듈이
아예 파싱하지 않는다(hermetic — 아래 "계층 메모" 참고).

QUAL-03 — 재서술(rephrase) 무변화 직접 측정(2026-08-10, 이 모듈 확장)
-----------------------------------------------------------------
T2의 부산물(§2.2·§5.2·§6.1)로 "재서술이 발문을 바꾸지 않은" 282쌍을 간접 발견했으나, 그건
교차코퍼스 텍스트매칭이라는 우회 경로로만 포착되는 **하한값**이다. `measure_rephrase_noop_
defect`가 이 태스크의 직접 측정이다 — `problem_bank_rephrased_v0` 전량을 순회하며
`relations[0].parent_slug`로 전 코퍼스에서 원본을 직접 찾아 `normalize_question_text`로 대조
한다. 실측 결과(2026-08-10) 무변화 **282**건 — 간접 하한과 **정확히 일치**했다(이 코퍼스
상태에서는 하한이 타이트했다는 뜻, `render_report` §7 참고). 처리 방침 권고는 `render_report`
§7.1(렌더 텍스트)에 있다 — 이 모듈은 코퍼스를 수정하지 않는다(위 "범위 밖" 원칙과 동일).

재발 방지 축(위생 게이트 확장)은 이 모듈이 아니라 `l3/equivalent/rephrase_hygiene.
question_hygiene_violations`(⑦축)·`l3/equivalent/rephrase.classify_invariance_failure`에
있다 — 이 모듈은 *측정*만, 그쪽이 *신규 생성 시점의 차단*을 담당한다(관심사 분리).

범위 밖
-------
실중복의 *해소*(어느 쪽을 은퇴시킬지)는 콘텐츠 판정이라 이 모듈 범위 밖이다 — 가시화까지만
한다. 코퍼스 파일(`data/corpus/problem_bank_*/**`)을 읽기만 하고 수정하지 않는다.

**게이트가 아니다**(`problem_bank_coverage`·`standard_attainment_report`와 동일 원칙) — 실중복이
발견돼도 exit 1을 내지 않는다(종료 코드는 0=성공 / 2=입력 오류만).

계층 메모(CLAUDE.md 7계층): 코퍼스 JSONL을 *읽기만* 하는 빌드타임 도구다(hermetic — DB·ORM·
API·LLM 어느 것도 건드리지 않는다). `schema.enums`(`RelationType` 등)를 import하지 않는다 —
코퍼스 원본 문자열을 그대로 쓴다(스키마 밖 값이 들어와도 조용히 죽지 않고 그대로 드러내기 위함
— `problem_bank_coverage.py`와 동일 원칙).

사용:
    python -m whymath_backend.harness.problem_duplication_audit
    python -m whymath_backend.harness.problem_duplication_audit --json out/duplication.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from whymath_backend.harness.problem_bank_coverage import (
    CORPUS_DIR_GLOB,
    CORPUS_FILE_NAME,
    DEFAULT_CORPUS_ROOT,
    discover_corpora,
)

__all__ = [
    "CorpusLoad",
    "CorpusStatus",
    "DemoPoolStatus",
    "DuplicatePair",
    "DuplicationRecord",
    "DuplicationReport",
    "ParseError",
    "RelationTag",
    "RephraseNoopRecord",
    "RephraseNoopReport",
    "RephraseNoopStatus",
    "SlugCollision",
    "build_global_slug_index",
    "build_lineage_graph",
    "build_report",
    "count_cross_corpus_text_matches",
    "count_same_corpus_text_duplicates",
    "demo_pool_corpora",
    "discover_corpora",
    "dump_json",
    "find_duplicate_pairs",
    "find_slug_collisions",
    "is_legitimate_sibling",
    "load_corpus_file",
    "main",
    "measure_rephrase_noop_defect",
    "normalize_question_text",
    "parse_problem_line",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(다른 harness 모듈과 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SEED_DEMO_PATH = _REPO_ROOT / "scripts" / "demo" / "seed_demo.py"

# T1 baseline — 원 설계 문서(미병합 브랜치, 재계산 불가한 과거 스냅샷)의 서술적 인용. 정본이
# 아니라 "그때는 이랬다"는 비교 참조값이다(§1 렌더 문장의 재료). 이 상수를 임계·게이트로 쓰지
# 않는다 — 이 모듈은 관측이지 그 값과의 비교로 통과/실패를 가르지 않는다.
_T1_BASELINE_COUNT = 392
_T1_BASELINE_SOURCE = (
    "장기 미병합 브랜치 `claude/whymath-data-platform-design-8ceaf5`의 원 설계 문서"
    "(2026-08-03 스냅샷, `generated_v0 ∩ rephrased_v0` 슬러그 교집합) — 그 브랜치는 트렁크에 "
    "랜딩한 적이 없어 이 상수는 재계산 불가한 과거 스냅샷의 서술적 인용이다(정본 아님)."
)

# T3 — 코드로 계산하지 않고 문서화만 한다(모듈 docstring 참고). 렌더 텍스트로만 쓰인다.
_T3_NOTE = (
    "`verify.conditions`(또는 그 서명)가 동일하다는 사실은 **절대 중복 판정 기준으로 쓰지 "
    '않는다**. 실측 반례: `wm-skel-f50f96b5a691`("이차방정식 x^2 + 2x - 48 = 0 의 두 근 중 '
    '큰 근은?")과 `wm-calc-ext-8c193941df77`("삼차함수 f(x) = x^3 + 3x^2 - 144x 가 극소가 '
    '되는 x의 값을 구하시오.")는 `verify.conditions`가 둘 다 `"x**2 + 2*x - 48 = 0"`으로 '
    "바이트 단위 동일하다(후자의 도함수 f'(x)=3x²+6x-144=3(x²+2x-48)가 그 이차식이기 때문) — "
    "그러나 교수학적으로는 완전히 다른 문항이다(전자는 이차방정식 직접 풀이, 후자는 삼차함수 "
    "극값 탐색). 두 slug 모두 `problem_bank_generated_v0`·`problem_bank_rephrased_v0`에 실재함을 "
    "이 모듈 작성 중 재확인했다. 이 축은 코드로 계산하지 않는다(원 설계 문서가 이미 관측 "
    "전용으로 결론지었고, 계산 자체가 위와 같은 오탐을 유발한다) — 이 문서화가 유일한 "
    "산출물이다."
)

CorpusStatus = Literal["적재됨", "비어있음", "데이터없음"]
DemoPoolStatus = Literal["파일확인됨", "파일없음"]


# ──────────────────────────────────────────────────────────────────────────
# 입력 모델 — 코퍼스 문항 투영(순수 데이터·불변)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ParseError:
    """코퍼스 라인 1건의 파싱/타입 실패 — 조용히 버리지 않고 보고하기 위한 기록.

    `error_type`은 예외 타입명(CLAUDE.md "침묵 실패 금지 — 예외 타입명을 로그에 포함").
    `detail`에는 문항 본문을 담지 않는다(저작권·PII 위생 — 필드명·기대 타입 수준만).
    """

    corpus: str
    line_no: int
    error_type: str
    detail: str


@dataclass(frozen=True, slots=True)
class RelationTag:
    """`relations[]` 원소 1건 — S4-14/S4-18 계보 태깅(코퍼스 자체 선언).

    `relation_type`(변형/유사/선수/심화/대조 — `RelationType`)은 값 검증하지 않는다(hermetic
    원칙 — populate.py의 `_relation_tag_from_dict`처럼 적재 거부를 하는 게 아니라, 코퍼스에
    *있는 그대로*를 감사 대상으로 삼는다). 이 모듈의 계보 그래프(`build_lineage_graph`)는
    관계 유형을 구분하지 않고 전부 배제 신호로 쓴다 — 관계가 선언돼 있다는 사실 자체가
    "두 문항이 저작 시점에 서로를 인지했다"는 뜻이라 독립적 우연 생성 가능성을 배제하기
    때문이다(모듈 docstring T2 절 참고).
    """

    parent_slug: str
    relation_type: str


@dataclass(frozen=True, slots=True)
class DuplicationRecord:
    """중복 감사에 필요한 문항 필드만 추린 투영(불변).

    `problem_bank_coverage.ProblemRecord`의 자매 클래스이나 그쪽엔 없는 `slug`·`question_text`·
    `relations`·`identity_id`가 필요해 별도 정의한다(재사용 시도 — 필드가 안 맞아 포기, 모듈
    docstring 미러). 정본 스키마는 `schema/problem.py`의 `Problem`이지만 여기선 pydantic 검증을
    하지 않는다 — 코퍼스가 스키마 밖 값을 담고 있어도 이 도구의 목적(있는 그대로 감사)에
    지장이 없어야 하기 때문이다.
    """

    corpus: str
    line_no: int
    problem_id: str | None
    slug: str | None
    question_text: str | None
    question_format: str | None
    identity_id: str | None
    relations: tuple[RelationTag, ...]


@dataclass(frozen=True, slots=True)
class CorpusLoad:
    """코퍼스 1종의 적재 결과 — 상태·문항·파싱 실패(불변).

    `status`는 "데이터없음"(파일 자체가 없음)과 "비어있음"(파일은 있으나 문항 0건)을 구분한다
    (`problem_bank_coverage.CorpusLoad`와 동일 관례).
    """

    name: str
    path: Path
    status: CorpusStatus
    records: tuple[DuplicationRecord, ...]
    parse_errors: tuple[ParseError, ...]


# ──────────────────────────────────────────────────────────────────────────
# 텍스트 정규화 — T2 조건 (b)
# ──────────────────────────────────────────────────────────────────────────
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_question_text(text: str | None) -> str | None:
    """문제 본문 텍스트 정규화 — Unicode NFC + 공백 연속 축약 + 양끝 trim.

    None/공백만 있는 문자열은 None으로 통일한다(정직 회계 —
    `DuplicationReport.records_without_question_text`가 별도로 센다). 구두점·숫자·대소문자·
    조사는 건드리지 않는다 — "완전 일치"라는 T2 최소 기준이 요구하는 보수적 정규화만 한다
    (의미 정규화를 하면 오탐 축이 T3와 같은 함정에 빠진다 — 표면 텍스트만 비교).
    """
    if text is None:
        return None
    collapsed = _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", text)).strip()
    return collapsed or None


# ──────────────────────────────────────────────────────────────────────────
# 로더
# ──────────────────────────────────────────────────────────────────────────
def _opt_str(value: object, field: str) -> str | None:
    """문자열 필드 추출 — None/부재는 None, 타입 위반은 TypeError(라인 단위 보고용)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}가 문자열이 아님(type={type(value).__name__})")
    return value


def _relations_from_raw(value: object, *, field: str) -> tuple[RelationTag, ...]:
    """`relations` 필드 → `RelationTag` 튜플(관대한 파싱 — hermetic 원칙).

    populate.py의 `_relation_tag_from_dict`(엄격 검증·위반 시 적재 거부)와 달리, 이 관측
    도구는 `relation_type`이 `RelationType` 밖이어도 거부하지 않고 그대로 통과시켜 그래프
    엣지로 쓴다 — 감사 대상은 "적재 가능한 코퍼스"가 아니라 "코퍼스에 있는 그대로의 선언"
    이기 때문이다. 필수 최소 요건은 `parent_slug` 문자열 존재뿐이다.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"{field}가 배열이 아님(type={type(value).__name__})")
    tags: list[RelationTag] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field} 원소가 object가 아님(type={type(item).__name__})")
        parent_slug = item.get("parent_slug")
        if not isinstance(parent_slug, str) or not parent_slug:
            raise TypeError(f"{field} 원소에 parent_slug 문자열이 없음")
        relation_type = item.get("relation_type")
        tags.append(
            RelationTag(
                parent_slug=parent_slug,
                relation_type=relation_type if isinstance(relation_type, str) else "",
            )
        )
    return tuple(tags)


def parse_problem_line(raw: str, *, corpus: str, line_no: int) -> DuplicationRecord:
    """JSONL 한 줄 → `DuplicationRecord`(순수). 실패는 예외로 올려 호출자가 카운트한다."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise TypeError(f"레코드가 object가 아님(type={type(obj).__name__})")
    return DuplicationRecord(
        corpus=corpus,
        line_no=line_no,
        problem_id=_opt_str(obj.get("problem_id"), "problem_id"),
        slug=_opt_str(obj.get("slug"), "slug"),
        question_text=_opt_str(obj.get("question_text"), "question_text"),
        question_format=_opt_str(obj.get("question_format"), "question_format"),
        identity_id=_opt_str(obj.get("identity_id"), "identity_id"),
        relations=_relations_from_raw(obj.get("relations"), field="relations"),
    )


def load_corpus_file(path: Path, *, name: str) -> CorpusLoad:
    """`problems.jsonl` 1개 → `CorpusLoad`(파일 부재도 예외 없이 상태로 표현).

    라인 파싱 실패는 그 라인만 `parse_errors`에 적재하고 나머지 라인 집계는 계속한다
    (`problem_bank_coverage.load_corpus_file`과 동일 관례 — 부분 실패로 전체를 버리지 않되
    버린 라인 수를 반드시 표면화한다).
    """
    if not path.is_file():
        return CorpusLoad(name=name, path=path, status="데이터없음", records=(), parse_errors=())
    records: list[DuplicationRecord] = []
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


# ──────────────────────────────────────────────────────────────────────────
# T1 — 코퍼스 간 슬러그 충돌
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SlugCollision:
    corpus_a: str
    corpus_b: str
    slug: str


def _slug_set(load: CorpusLoad) -> frozenset[str]:
    return frozenset(r.slug for r in load.records if r.slug)


def find_slug_collisions(
    loads: tuple[CorpusLoad, ...],
) -> tuple[tuple[SlugCollision, ...], dict[tuple[str, str], int]]:
    """전 코퍼스 쌍(C(n,2))의 슬러그 교집합 — (충돌 레코드 전량, 코퍼스쌍→건수 전량 사전).

    사전은 충돌이 0인 쌍도 포함한다(정직 회계 — "검사 안 함"과 "검사해서 0"을 구분하려면
    스캔한 조합 자체를 드러내야 한다). 정렬은 코퍼스명 오름차순(결정론) — 입력 `loads` 순서에
    무관하게 같은 출력을 낸다.
    """
    ordered = tuple(sorted(loads, key=lambda ld: ld.name))
    pair_counts: dict[tuple[str, str], int] = {}
    collisions: list[SlugCollision] = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            shared = sorted(_slug_set(a) & _slug_set(b))
            pair_counts[(a.name, b.name)] = len(shared)
            collisions.extend(
                SlugCollision(corpus_a=a.name, corpus_b=b.name, slug=s) for s in shared
            )
    return tuple(collisions), pair_counts


# ──────────────────────────────────────────────────────────────────────────
# 계보 그래프 — T2 조건 (c)
# ──────────────────────────────────────────────────────────────────────────
def build_lineage_graph(loads: tuple[CorpusLoad, ...]) -> dict[str, frozenset[str]]:
    """`relations[].parent_slug` 선언 → 무향 인접 그래프(slug ↔ parent_slug).

    관계 유형(변형/유사/선수/심화/대조) 무관하게 전부 엣지로 삼는다 — 모듈 docstring T2 절이
    설명하는 이유(선언 자체가 "독립적 우연 생성 아님"의 신호) 때문이다. `parent_slug`가 어느
    코퍼스에도 실재하지 않는 고아 참조라도 그래프 노드로는 받아들인다(연결성 판정에는 지장
    없다 — 참조 무결성 검증은 `populate.py`의 몫이지 이 관측 도구의 몫이 아니다).
    """
    adjacency: dict[str, set[str]] = {}
    for load in loads:
        for record in load.records:
            if not record.slug:
                continue
            for relation in record.relations:
                a, b = record.slug, relation.parent_slug
                adjacency.setdefault(a, set()).add(b)
                adjacency.setdefault(b, set()).add(a)
    return {node: frozenset(neighbors) for node, neighbors in adjacency.items()}


def _connected_component(start: str, adjacency: dict[str, frozenset[str]]) -> frozenset[str]:
    """`start`가 속한 연결요소(BFS 폐포). `start`가 그래프에 없으면 자기 자신만 담은 집합."""
    if start not in adjacency:
        return frozenset({start})
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for neighbor in adjacency.get(current, frozenset()):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return frozenset(seen)


def is_legitimate_sibling(slug_a: str, slug_b: str, adjacency: dict[str, frozenset[str]]) -> bool:
    """두 슬러그가 같은 계보 연결요소에 속하는가(T2 조건 (c) 배제 판정).

    `slug_a == slug_b`이면 항상 True다(한 노드의 연결요소는 자기 자신을 항상 포함) — 이는
    의도된 완화다: 같은 슬러그가 서로 다른 코퍼스에 나타나는 상황은 T1(슬러그 충돌) 축이 이미
    전담해 보고하므로, T2가 그 경우를 "정당한 형제"로 접어 중복 집계하지 않는 편이 두 축의
    책임을 깨끗이 분리한다(현재 T1=0이라 실제로는 발생하지 않지만, 축 간 경계를 명시해 둔다).
    """
    return slug_b in _connected_component(slug_a, adjacency)


# ──────────────────────────────────────────────────────────────────────────
# T2 — 실중복(정규화된 question_text 완전 일치)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DuplicatePair:
    """실중복 확정 쌍 1건 — T2 조건 (a)+(b)+(c)를 전부 만족한 결과."""

    corpus_a: str
    slug_a: str
    question_format_a: str | None
    corpus_b: str
    slug_b: str
    question_format_b: str | None
    normalized_text: str
    same_question_format: bool
    demo_pool_co_exposed: bool


def _group_by_normalized_text(
    loads: tuple[CorpusLoad, ...],
) -> dict[str, tuple[DuplicationRecord, ...]]:
    """정규화된 `question_text` → 그 텍스트를 가진 레코드 전량(코퍼스·slug 오름차순 정렬).

    `slug` 없는 레코드·정규화 후 빈 텍스트는 그룹핑에서 제외한다(정직 회계 카운터는
    `build_report`가 별도로 센다 — 여기서 조용히 버리는 게 아니라 이 그룹핑 자체의 전제조건이
    slug·텍스트 보유이기 때문이다). 반환 dict의 각 값은 항상 (corpus, slug) 오름차순 — 호출자의
    페어링 순서가 입력 순서에 의존하지 않는다(결정론).
    """
    buckets: dict[str, list[DuplicationRecord]] = {}
    for load in loads:
        for record in load.records:
            if not record.slug:
                continue
            text = normalize_question_text(record.question_text)
            if text is None:
                continue
            buckets.setdefault(text, []).append(record)
    return {
        text: tuple(sorted(records, key=lambda r: (r.corpus, r.slug or "")))
        for text, records in buckets.items()
    }


def count_cross_corpus_text_matches(loads: tuple[CorpusLoad, ...]) -> int:
    """조건 (a)+(b)만 적용한 원시 후보 쌍 수(계보 배제 *전*).

    `lineage_excluded_pair_count`(=이 값 - 확정 실중복 수)의 분모다 — 배제 메커니즘이 실제로
    후보를 걸러내는지(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지")를 보여주는 재료.
    """
    groups = _group_by_normalized_text(loads)
    total = 0
    for records in groups.values():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                if records[i].corpus != records[j].corpus:
                    total += 1
    return total


def count_same_corpus_text_duplicates(loads: tuple[CorpusLoad, ...]) -> dict[str, int]:
    """코퍼스 *내부* 텍스트 중복 그룹 수(조건 (a) 밖 — 실중복 집계에는 들어가지 않는 참고 축).

    한 코퍼스 안에서 같은 정규화 텍스트를 가진 레코드가 2건 이상이면 그 코퍼스에 1그룹으로
    센다(레코드 수가 아니라 그룹 수 — 반복 패턴의 "건수"를 과대평가하지 않기 위함).
    """
    groups = _group_by_normalized_text(loads)
    counts: dict[str, int] = {}
    for records in groups.values():
        per_corpus: dict[str, int] = {}
        for record in records:
            per_corpus[record.corpus] = per_corpus.get(record.corpus, 0) + 1
        for corpus, n in per_corpus.items():
            if n > 1:
                counts[corpus] = counts.get(corpus, 0) + 1
    return counts


def find_duplicate_pairs(
    loads: tuple[CorpusLoad, ...], *, demo_pool: frozenset[str]
) -> tuple[DuplicatePair, ...]:
    """실중복 확정 쌍 — 최소 기준 (a)+(b)+(c) 전부 적용(모듈 docstring T2 절).

    (a) 서로 다른 코퍼스 (b) 정규화 텍스트 완전 일치(`_group_by_normalized_text`가 보장)
    (c) `relations` 계보 연결요소가 다름(`is_legitimate_sibling`이 False) — 셋 다 만족해야
    최종 목록에 오른다. 결정론 정렬(텍스트→코퍼스A→슬러그A→코퍼스B→슬러그B) — 입력 순서·딕셔너리
    삽입 순서에 무관하게 항상 같은 출력.
    """
    adjacency = build_lineage_graph(loads)
    groups = _group_by_normalized_text(loads)
    confirmed: list[DuplicatePair] = []
    for text, records in groups.items():
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                rec_a, rec_b = records[i], records[j]
                if rec_a.corpus == rec_b.corpus:
                    continue
                assert rec_a.slug is not None  # _group_by_normalized_text가 slug 보유를 보장
                assert rec_b.slug is not None
                if is_legitimate_sibling(rec_a.slug, rec_b.slug, adjacency):
                    continue
                confirmed.append(
                    DuplicatePair(
                        corpus_a=rec_a.corpus,
                        slug_a=rec_a.slug,
                        question_format_a=rec_a.question_format,
                        corpus_b=rec_b.corpus,
                        slug_b=rec_b.slug,
                        question_format_b=rec_b.question_format,
                        normalized_text=text,
                        same_question_format=(rec_a.question_format == rec_b.question_format),
                        demo_pool_co_exposed=(
                            rec_a.corpus in demo_pool and rec_b.corpus in demo_pool
                        ),
                    )
                )
    confirmed.sort(key=lambda p: (p.normalized_text, p.corpus_a, p.slug_a, p.corpus_b, p.slug_b))
    return tuple(confirmed)


# ──────────────────────────────────────────────────────────────────────────
# 데모/파일럿 풀 실재성
# ──────────────────────────────────────────────────────────────────────────
# `scripts/demo/seed_demo.py`는 whymath_backend 패키지 밖(repo root `scripts/`)이라 cross-package
# import 대신 텍스트 패턴 매칭으로 `_CORPORA` 튜플의 코퍼스 디렉터리명을 뽑는다
# (`ops/declared_unwired_audit.ci_executed_modules`가 `ci.yml`을 정규식으로 읽는 것과 동형
# 원리 — "읽기 전용 사이드카 파일에서 구조화 정보를 정적으로 뽑는다"). 이렇게 하면 데모 풀
# 코퍼스 목록을 이 모듈에 하드코딩하지 않아 `seed_demo.py`가 바뀌면 이 리포트도 자동으로
# 최신 상태를 따라간다(단일 진실 원천 유지).
_CORPUS_DIR_REF = re.compile(r'_CORPUS_ROOT\s*/\s*"([^"]+)"\s*/\s*"problems\.jsonl"')


def demo_pool_corpora(seed_demo_path: Path = _DEFAULT_SEED_DEMO_PATH) -> frozenset[str]:
    """`scripts/demo/seed_demo.py`의 `_CORPORA` 튜플에서 실제 로드되는 코퍼스 디렉터리명 집합.

    파일이 없거나 패턴이 0건 매치되면 빈 집합(정직 회계 — 호출자가 "파일없음" 상태와 구분해
    렌더에 표기한다. `main`이 그 구분을 담당한다).
    """
    if not seed_demo_path.is_file():
        return frozenset()
    text = seed_demo_path.read_text(encoding="utf-8")
    return frozenset(_CORPUS_DIR_REF.findall(text))


# ──────────────────────────────────────────────────────────────────────────
# QUAL-03 — 재서술(rephrase) 무변화 직접 측정
# ──────────────────────────────────────────────────────────────────────────
# QUAL-01(위 T2 §2.2·§5.2·§6.1)이 간접 발견한 "재서술이 발문을 바꾸지 않음" 282쌍은 교차코퍼스
# 텍스트매칭의 부산물이라(원본이 *다른 코퍼스*에 있고 텍스트가 우연히 매칭될 때만 포착)
# **하한값**이다. 아래는 대상 코퍼스(기본 rephrased_v0) 전량을 순회하며 `relations[0].
# parent_slug`로 선언된 원본을 전 코퍼스에서 직접 찾아 정규화 텍스트를 대조하는 **전수 직접
# 측정**이다(QUAL-03, 2026-08-10). 판정 기준은 T2의 `normalize_question_text`와 동일 함수를
# 재사용한다(간접·직접 두 수치가 서로 다른 정규화를 쓰면 어긋나 혼란을 유발한다 — 정직 회계).
_REPHRASE_NOOP_TARGET_CORPUS = "problem_bank_rephrased_v0"

RephraseNoopStatus = Literal["무변화", "정상변화", "부모미선언", "고아참조"]


@dataclass(frozen=True, slots=True)
class RephraseNoopRecord:
    """대상 코퍼스 레코드 1건의 무변화 직접측정 판정(불변) — 4분류 중 정확히 하나."""

    slug: str
    status: RephraseNoopStatus
    parent_slug: str | None
    parent_corpus: str | None


@dataclass(frozen=True, slots=True)
class RephraseNoopReport:
    """대상 코퍼스 전량의 무변화 직접측정 결과(불변) — 정직 회계 4분류(조용히 빼거나 넣지 않음)."""

    target_corpus: str
    total: int
    records: tuple[RephraseNoopRecord, ...]

    @property
    def unchanged_count(self) -> int:
        return sum(1 for r in self.records if r.status == "무변화")

    @property
    def changed_count(self) -> int:
        return sum(1 for r in self.records if r.status == "정상변화")

    @property
    def no_parent_declared_count(self) -> int:
        return sum(1 for r in self.records if r.status == "부모미선언")

    @property
    def orphan_parent_count(self) -> int:
        return sum(1 for r in self.records if r.status == "고아참조")

    @property
    def measurable_count(self) -> int:
        """무변화/정상변화 판정이 가능했던 레코드 수(비율의 분모) — 부모미선언·고아참조 제외."""
        return self.unchanged_count + self.changed_count

    @property
    def unchanged_rate(self) -> float | None:
        """측정 가능 모집단 대비 무변화 비율 — 분모 0이면 None(0%로 위장하지 않는다)."""
        if self.measurable_count == 0:
            return None
        return self.unchanged_count / self.measurable_count


def build_global_slug_index(
    loads: tuple[CorpusLoad, ...],
) -> dict[str, tuple[str, DuplicationRecord]]:
    """slug → (코퍼스명, 레코드) — 전 코퍼스 통틀어 첫 매치(코퍼스명 오름차순·결정론).

    T1(슬러그 충돌) 축이 현재 코퍼스 상태에서 0건임을 이 모듈이 이미 확인했지만(`build_report`),
    이 인덱스는 그 사실에 의존하지 않고 방어적으로 first-wins 규칙을 쓴다(입력 `loads` 순서와
    무관하게 항상 같은 결과 — 코퍼스명 오름차순을 먼저 적용한 뒤 처음 만난 슬러그를 채택).
    """
    index: dict[str, tuple[str, DuplicationRecord]] = {}
    for load in sorted(loads, key=lambda ld: ld.name):
        for record in load.records:
            if record.slug and record.slug not in index:
                index[record.slug] = (load.name, record)
    return index


def measure_rephrase_noop_defect(
    loads: tuple[CorpusLoad, ...], *, target_corpus: str = _REPHRASE_NOOP_TARGET_CORPUS
) -> RephraseNoopReport:
    """대상 코퍼스 전량 직접 측정 — `relations[0].parent_slug`를 전 코퍼스에서 직접 대조(QUAL-03).

    각 레코드를 4분류 중 정확히 하나로 판정한다(정직 회계 — 조용히 분모에서 빼거나 넣지 않음):
      - **무변화**: `relations[0].parent_slug`가 어딘가에서 resolve되고, 자신의
        `normalize_question_text` 결과가 그 부모의 것과 완전 일치.
      - **정상변화**: 위와 같이 resolve되지만 텍스트가 다름(둘 중 하나라도 정규화 결과가
        None이면 — 즉 텍스트 자체가 없으면 — 안전 측을 택해 "무변화"로 잘못 세지 않는다).
      - **부모미선언**: `relations`가 아예 비어 있음(선언 자체가 없어 측정 불가).
      - **고아참조**: `relations[0].parent_slug`가 로드된 어느 코퍼스에도 없음(측정 불가).

    `relations`가 2개 이상이면 **첫 번째(인덱스 0)만** 참조 부모로 쓴다 — 실측 데이터
    (`problem_bank_rephrased_v0` 전량 — 건수는 `docs/data/corpus_facts.md`의
    `problem_bank.rephrased_v0`)는 전부 정확히 관계 1개만 선언하므로 이 결정이 현재
    측정치에 영향을 주지 않는다(회귀 테스트 `test_real_corpus_snapshot_rephrase_noop`가 이
    불변식 자체도 함께 고정한다). 다중 관계 레코드가 향후 나타나면 이 함수의 판정 기준을
    재검토해야 한다(정직 한계).

    `loads`는 QUAL-01의 `_resolve_loads`/`discover_corpora`가 이미 로드한 전 코퍼스를 그대로
    받는다(별도 파일 I/O 없음 — `build_report`와 동일 관례, 테스트가 실 코퍼스 없이 이 함수만
    검증할 수 있게 한다). 대상 코퍼스가 `loads`에 없으면 `total=0`의 빈 리포트를 돌린다(크래시
    금지 — rephrased_v0가 없는 코퍼스 루트에서도 CLI가 안전하게 동작해야 한다).
    """
    index = build_global_slug_index(loads)
    target = next((ld for ld in loads if ld.name == target_corpus), None)
    if target is None:
        return RephraseNoopReport(target_corpus=target_corpus, total=0, records=())

    results: list[RephraseNoopRecord] = []
    for record in target.records:
        slug = record.slug or f"(slug없음:L{record.line_no})"
        if not record.relations:
            results.append(
                RephraseNoopRecord(
                    slug=slug, status="부모미선언", parent_slug=None, parent_corpus=None
                )
            )
            continue
        parent_slug = record.relations[0].parent_slug
        match = index.get(parent_slug)
        if match is None:
            results.append(
                RephraseNoopRecord(
                    slug=slug, status="고아참조", parent_slug=parent_slug, parent_corpus=None
                )
            )
            continue
        parent_corpus, parent_record = match
        own_norm = normalize_question_text(record.question_text)
        parent_norm = normalize_question_text(parent_record.question_text)
        status: RephraseNoopStatus = (
            "무변화" if (own_norm is not None and own_norm == parent_norm) else "정상변화"
        )
        results.append(
            RephraseNoopRecord(
                slug=slug, status=status, parent_slug=parent_slug, parent_corpus=parent_corpus
            )
        )
    return RephraseNoopReport(
        target_corpus=target_corpus, total=len(target.records), records=tuple(results)
    )


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 중복 감사 리포트(순수 코어)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DuplicationReport:
    """중복 감사 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    corpora: tuple[CorpusLoad, ...]
    total_problems: int
    parse_errors: tuple[ParseError, ...]
    # T1
    corpus_pairs_scanned: int
    slug_collisions: tuple[SlugCollision, ...]
    slug_collision_pair_counts: dict[tuple[str, str], int]
    # T2
    lineage_node_count: int
    lineage_edge_count: int
    cross_corpus_text_match_candidates: int
    duplicate_pairs: tuple[DuplicatePair, ...]
    lineage_excluded_pair_count: int
    same_corpus_internal_duplicate_groups: dict[str, int]
    # 데모 풀
    demo_pool_corpora: frozenset[str]
    demo_pool_status: DemoPoolStatus
    # 정직 회계
    records_without_slug: int
    records_without_question_text: int
    internal_duplicate_slug_total: int
    # QUAL-03 — 재서술 무변화 직접 측정
    rephrase_noop: RephraseNoopReport

    @property
    def duplicate_pair_count(self) -> int:
        return len(self.duplicate_pairs)

    @property
    def duplicate_pairs_same_format(self) -> tuple[DuplicatePair, ...]:
        """형식(question_format)까지 같은 쌍 — 독립 생성 추정, 가장 강한 실중복 신호."""
        return tuple(p for p in self.duplicate_pairs if p.same_question_format)

    @property
    def duplicate_pairs_diff_format(self) -> tuple[DuplicatePair, ...]:
        """형식이 다른 쌍(단답형/객관식 등) — 스켈레톤 트윈 가능성, §2.2 참고."""
        return tuple(p for p in self.duplicate_pairs if not p.same_question_format)

    @property
    def demo_co_exposed_pairs(self) -> tuple[DuplicatePair, ...]:
        return tuple(p for p in self.duplicate_pairs if p.demo_pool_co_exposed)


def build_report(
    loads: tuple[CorpusLoad, ...],
    *,
    demo_pool: frozenset[str],
    demo_pool_status: DemoPoolStatus,
) -> DuplicationReport:
    """코퍼스 적재 결과 + 데모 풀 코퍼스 집합 → `DuplicationReport`(순수·부작용 0).

    파일 I/O 없이 호출 가능하다 — `loads`·`demo_pool`은 호출자가 이미 읽어 온 값이다(테스트가
    실 코퍼스·실 `seed_demo.py` 없이 이 함수만으로 T1/T2 판정 로직 전체를 검증할 수 있게 하기
    위함, `standard_attainment_report.build_report`와 동일 관례). T3는 계산하지 않는다(모듈
    docstring) — 이 리포트 객체에 T3 필드가 없는 것 자체가 그 원칙의 표현이다. QUAL-03(재서술
    무변화 직접 측정)은 `measure_rephrase_noop_defect(loads)`를 그대로 호출한다 — 기본
    대상 코퍼스(`problem_bank_rephrased_v0`)가 `loads`에 없어도 빈 리포트로 안전하게 처리된다.

    `loads`는 맨 먼저 코퍼스명 오름차순으로 재정렬한다 — 하위 판정 함수(`find_duplicate_pairs`
    등)는 이미 자체적으로 결정론 정렬을 하지만, 이 함수가 직접 순회하는 `corpora`·`parse_errors`
    필드는 그 보호가 없어 호출자가 넘긴 `loads` 순서를 그대로 노출했었다(입력 순서 의존 —
    회귀 테스트 `test_build_report_output_independent_of_loads_insertion_order`가 잡아낸 결함).
    """
    loads = tuple(sorted(loads, key=lambda ld: ld.name))
    total = sum(len(ld.records) for ld in loads)
    parse_errors = tuple(err for ld in loads for err in ld.parse_errors)
    no_slug = sum(1 for ld in loads for r in ld.records if not r.slug)
    no_text = sum(
        1 for ld in loads for r in ld.records if normalize_question_text(r.question_text) is None
    )
    internal_dup_slug_total = sum(
        len(ld.records) - len({r.slug for r in ld.records if r.slug}) for ld in loads
    )

    slug_collisions, pair_counts = find_slug_collisions(loads)
    adjacency = build_lineage_graph(loads)
    raw_candidates = count_cross_corpus_text_matches(loads)
    same_corpus_internal = count_same_corpus_text_duplicates(loads)
    duplicate_pairs = find_duplicate_pairs(loads, demo_pool=demo_pool)
    rephrase_noop = measure_rephrase_noop_defect(loads)

    return DuplicationReport(
        corpora=loads,
        total_problems=total,
        parse_errors=parse_errors,
        corpus_pairs_scanned=len(pair_counts),
        slug_collisions=slug_collisions,
        slug_collision_pair_counts=pair_counts,
        lineage_node_count=len(adjacency),
        lineage_edge_count=sum(len(v) for v in adjacency.values()) // 2,
        cross_corpus_text_match_candidates=raw_candidates,
        duplicate_pairs=duplicate_pairs,
        lineage_excluded_pair_count=raw_candidates - len(duplicate_pairs),
        same_corpus_internal_duplicate_groups=same_corpus_internal,
        demo_pool_corpora=demo_pool,
        demo_pool_status=demo_pool_status,
        records_without_slug=no_slug,
        records_without_question_text=no_text,
        internal_duplicate_slug_total=internal_dup_slug_total,
        rephrase_noop=rephrase_noop,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def render_report(report: DuplicationReport, *, max_listed: int = 60) -> str:
    """중복 감사 결과를 마크다운으로 렌더(순수·입력 외 계산 없음·정렬 고정).

    쌍 목록은 `max_listed`개까지만 본문에 싣고 나머지는 건수로 요약한다(전량은 `--json`
    산출물에 있다). 잘렸다는 사실 자체를 문장으로 남긴다 — 조용한 절단 금지
    (`problem_bank_coverage` 관례).
    """
    lines: list[str] = [
        "# 문항 코퍼스 중복 감사 리포트 (QUAL-01)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(실중복이 발견돼도 exit 1을 내지 않는다 — "
        "`problem_bank_coverage`/`standard_attainment_report`와 동일 원칙).",
        "> 설계 배경: 장기 미병합 브랜치 `claude/whymath-data-platform-design-8ceaf5`"
        "(2026-08-03 스냅샷)가 설계한 T1(slug_collision)/T2(identical_question_text)/"
        "T3(verify.conditions 서명 동일 — 관측 전용) 3축 문항 수준 중복 감사를, 이 저장소의 "
        "**현재 main 코퍼스**에 대해 재실측한다.",
        "",
        "## 0. 입력 요약",
        "",
        f"- 코퍼스: **{len(report.corpora)}**종 · 문항 총계: **{report.total_problems}**문",
        "",
        "| 코퍼스 | 상태 | 문항 | 파싱 실패 |",
        "|---|---|---:|---:|",
    ]
    for load in report.corpora:
        lines.append(
            f"| `{load.name}` | {load.status} | {len(load.records)} | {len(load.parse_errors)} |"
        )

    # ── T1 ──
    total_collisions = len(report.slug_collisions)
    lines += [
        "",
        "## 1. T1 — 코퍼스 간 슬러그 충돌",
        "",
        f"- 이전 실측(원 설계 문서 — 미병합 브랜치, 2026-08-03 스냅샷, "
        f"`generated_v0 ∩ rephrased_v0` 슬러그 교집합): **{_T1_BASELINE_COUNT}건**",
        f"  ({_T1_BASELINE_SOURCE})",
        f"- 현재 재측정(전 {len(report.corpora)}종 코퍼스 {report.total_problems}문, "
        f"C({len(report.corpora)},2)={report.corpus_pairs_scanned}쌍 전수 스캔): "
        f"**{total_collisions}건**",
    ]
    if total_collisions == 0:
        lines.append(
            "- **해소됨** — 원인은 조사하지 않았다(슬러그 네임스페이싱 변경 등으로 추정, "
            "재조사는 이 리포트 범위 밖)."
        )
    nonzero_pairs = sorted(
        (a, b, n) for (a, b), n in report.slug_collision_pair_counts.items() if n > 0
    )
    lines += ["", "| 코퍼스 A | 코퍼스 B | 충돌 슬러그 |", "|---|---|---:|"]
    if not nonzero_pairs:
        lines.append(f"| (없음 — {report.corpus_pairs_scanned}쌍 전부 0) | | |")
    else:
        for a, b, n in nonzero_pairs:
            lines.append(f"| `{a}` | `{b}` | {n} |")
        lines += ["", "### 1.1 충돌 슬러그 상세", ""]
        for sc in report.slug_collisions:
            lines.append(f"- `{sc.slug}` (`{sc.corpus_a}` ↔ `{sc.corpus_b}`)")

    # ── T2 ──
    if report.cross_corpus_text_match_candidates:
        _excl_ratio = report.lineage_excluded_pair_count / report.cross_corpus_text_match_candidates
        excl_rate = f"{_excl_ratio * 100:.1f}%"
    else:
        excl_rate = "데이터없음"
    lines += [
        "",
        "## 2. T2 — 실중복(정규화된 문제 본문 텍스트 완전 일치)",
        "",
        "**판정 기준(코드: `find_duplicate_pairs`)** — 아래 3개를 **전부** 만족해야 '실중복'이다:",
        "",
        "1. **(a) 은행 상이** — 서로 다른 코퍼스 파일(`problem_bank_*`) 소속.",
        "2. **(b) 텍스트 완전 일치** — `question_text`를 NFC 정규화 + 공백 연속 축약 후 바이트 "
        "단위 완전 일치(`normalize_question_text`). 의미 정규화(동의어·어순 등)는 하지 않는다 "
        "— 표면 텍스트만 비교한다(오탐 축소).",
        "3. **(c) 정당한 계보 형제가 아님** — 두 레코드의 `slug`가 코퍼스 자체가 선언한 "
        "`relations[].parent_slug` 무향 그래프(변형/유사/선수/심화/대조 관계 유형 불문 — "
        "관계가 선언돼 있다는 사실 자체가 '독립적 우연 생성'을 배제하는 신호이므로 유형은 "
        "구분하지 않는다) 상에서 같은 연결요소(BFS 폐포)에 속하면 배제한다(S4-14 CAT 형제 "
        "필터·S4-18 identity/변형 계보가 쓰는 것과 같은 필드).",
        "",
        f"- 계보 그래프 규모: 노드 **{report.lineage_node_count}** · 엣지 "
        f"**{report.lineage_edge_count}**(`relations` 필드를 가진 코퍼스는 `generated_v0`·"
        "`rephrased_v0` 둘뿐 — 나머지 5종엔 이 필드 자체가 없다).",
        f"- 조건 (a)+(b)만 적용한 원시 후보(계보 배제 *전*): "
        f"**{report.cross_corpus_text_match_candidates}**쌍",
        f"- 계보 (c)로 배제됨: **{report.lineage_excluded_pair_count}**쌍 ({excl_rate}) — "
        '배제 메커니즘이 실제로 작동한다는 신호(CLAUDE.md "작동 신호 없는 알고리즘 부착 금지").',
        f"- **실중복 확정: {report.duplicate_pair_count}쌍** "
        f"(형식 동일 {len(report.duplicate_pairs_same_format)}쌍 · "
        f"형식 상이 {len(report.duplicate_pairs_diff_format)}쌍 — 아래 §2.1/§2.2)",
        "",
        "### 2.1 형식 동일 쌍 — 독립 생성 추정(가장 강한 실중복 신호)",
        "",
    ]
    same_fmt = report.duplicate_pairs_same_format
    if not same_fmt:
        lines.append("- 없음.")
    else:
        lines += [
            "| 코퍼스 A | slug A | 코퍼스 B | slug B | 형식 | 데모풀 동시노출 | 발문(첫 50자) |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in same_fmt[:max_listed]:
            lines.append(
                f"| `{p.corpus_a}` | `{p.slug_a}` | `{p.corpus_b}` | `{p.slug_b}` | "
                f"{p.question_format_a or '(미상)'} | "
                f"{'예' if p.demo_pool_co_exposed else '아니오'} | {p.normalized_text[:50]} |"
            )
        remainder = len(same_fmt) - min(len(same_fmt), max_listed)
        if remainder > 0:
            lines.append(f"- …외 **{remainder}**건(전량은 `--json` 산출물).")

    lines += [
        "",
        "### 2.2 형식 상이 쌍(단답형 ↔ 객관식) — 스켈레톤 트윈 + 재서술 무변화 상호작용",
        "",
        "> 이 쌍들은 전부 `generated_v0`가 같은 스켈레톤을 **단답형/객관식 두 형식으로 각각 "
        "생성**(같은 slug 해시suffix, 예: `wm-calc-extv-cd86d461d1b1`/`wm-calc-extmc-"
        "cd86d461d1b1` — 발문 stem은 동일, `choices` 유무만 다름 — **같은 코퍼스 내부에도 동일 "
        "패턴이 존재**함을 확인했다, §6.1 참고)한 뒤, 각각의 `rephrased_v0` '변형'이 발문을 "
        "**바꾸지 않고 그대로 복사**해 교차 매칭된 것이다. `relations` 그래프는 형식별로 분리돼 "
        "있어(`extv` 계열과 `extmc` 계열이 서로를 참조하지 않는다) 조건 (c)가 이 쌍들을 배제하지 "
        "못한다 — **이것은 배제 로직의 결함이 아니라, 코퍼스에 'MC/비MC 트윈'을 잇는 계보 필드가 "
        "애초에 없다는 사실을 있는 그대로 드러낸 것**이다(슬러그 문자열 패턴 같은 새 휴리스틱을 "
        "발명해 조용히 배제하지 않는다 — CLAUDE.md 정직 회계).",
        "",
    ]
    diff_fmt = report.duplicate_pairs_diff_format
    if not diff_fmt:
        lines.append("- 없음.")
    else:
        lines += [
            "| 코퍼스 A | slug A(형식) | 코퍼스 B | slug B(형식) | 데모풀 동시노출 | "
            "발문(첫 50자) |",
            "|---|---|---|---|---|---|",
        ]
        for p in diff_fmt[:max_listed]:
            lines.append(
                f"| `{p.corpus_a}` | `{p.slug_a}`({p.question_format_a or '미상'}) | "
                f"`{p.corpus_b}` | `{p.slug_b}`({p.question_format_b or '미상'}) | "
                f"{'예' if p.demo_pool_co_exposed else '아니오'} | {p.normalized_text[:50]} |"
            )
        remainder = len(diff_fmt) - min(len(diff_fmt), max_listed)
        if remainder > 0:
            lines.append(f"- …외 **{remainder}**건(전량은 `--json` 산출물).")

    # ── T3 ──
    lines += [
        "",
        "## 3. T3 — verify.conditions 서명 동일은 판정 기준이 아니다(계산 안 함)",
        "",
        _T3_NOTE,
    ]

    # ── 4. 데모/파일럿 풀 실재성 ──
    demo_list = ", ".join(f"`{c}`" for c in sorted(report.demo_pool_corpora)) or "(없음/알수없음)"
    lines += [
        "",
        "## 4. 데모/파일럿 풀 실재성",
        "",
        f"- `scripts/demo/seed_demo.py` 상태: {report.demo_pool_status}",
        f"- 데모/파일럿 풀 코퍼스: {demo_list}",
        f"- 실중복 쌍 중 **양쪽 코퍼스가 모두 데모 풀에 동시 포함**된 쌍: "
        f"**{len(report.demo_co_exposed_pairs)}** / {report.duplicate_pair_count}",
    ]
    if report.demo_co_exposed_pairs:
        lines += ["", "### 4.1 데모 풀 동시노출 쌍", ""]
        for p in report.demo_co_exposed_pairs:
            lines.append(f"- `{p.corpus_a}`/`{p.slug_a}` ↔ `{p.corpus_b}`/`{p.slug_b}`")

    # ── 5. 정당한 유사 문항 판별 기준 요약 ──
    lines += [
        "",
        "## 5. 정당한 유사 문항 판별 기준 요약",
        "",
        "- **정본 필드**: 코퍼스 레코드의 `relations: [{parent_slug, relation_type, "
        "similarity_score}]`(`generated_v0`·`rephrased_v0`만 보유) — S4-14(스켈레톤 계보)·"
        "S4-18(identity/재서술 계보)이 쓰는 것과 동일한 필드. 관계 유형(`RelationType`: "
        "변형/유사/선수/심화/대조)은 구분하지 않고 전부 배제 신호로 쓴다(§2 조건 (c)).",
        "- **5.1 커버되는 경우**: 같은 스켈레톤의 다른 밴드/파라미터 형제(`관계=유사`) — 예: "
        "`x^2-x-6=0`/`x^2+4x-5=0`/`x^2-6x+8=0`은 전부 `wm-skel-92cd1ba2bbf5`와 `유사` 관계로 "
        "선언돼 있고 텍스트도 실제로 다르다(파라미터가 다르므로 애초에 텍스트 매칭에도 안 "
        "걸린다). 재서술(`관계=변형`, similarity 1.0)도 커버된다.",
        "- **5.2 커버되지 않는 경우(정직한 잔여)**: 같은 스켈레톤의 단답형/객관식 트윈 — "
        "`relations`가 형식 간에는 선언되지 않는다(§2.2). 부수로 발견한 사실: 재서술이 발문을 "
        f"전혀 바꾸지 않는 사례가 이 스캔에서 배제된 {report.lineage_excluded_pair_count}쌍 "
        "**전부**를 차지한다(`generated_v0`↔`rephrased_v0` 조합만 배제됐고, 그 각각이 "
        "레코드 자신의 `변형` 관계로 자기 원본을 직접 지목한 1-hop 엣지였다 — 실측 확인) — "
        "`harness/rephrased_corpus_hygiene.py`(발문 위생 게이트)는 문법 결함만 보고 '무변화'는 "
        "검사하지 않는다는 것도 이번 스캔 중 확인했다(교차참조일 뿐 이 리포트가 그 축을 "
        "계산하지는 않는다).",
    ]

    # ── 6. 정직 회계 ──
    lines += [
        "",
        "## 6. 정직 회계",
        "",
        "> 조용히 버리지 않는다 — 아래가 모두 0이어야 위 수치를 액면 그대로 읽을 수 있다.",
        "",
        "| 항목 | 건수 |",
        "|---|---:|",
        f"| 파싱 실패 라인 | {len(report.parse_errors)} |",
        f"| slug 없는 레코드 | {report.records_without_slug} |",
        f"| question_text 없는/공백 레코드 | {report.records_without_question_text} |",
        f"| 코퍼스 *내부* 슬러그 중복(같은 파일 안에서 slug 반복) | "
        f"{report.internal_duplicate_slug_total} |",
    ]
    if report.same_corpus_internal_duplicate_groups:
        lines += [
            "",
            "### 6.1 코퍼스 내부 텍스트 중복 그룹(참고용 — 조건 (a) 밖이라 실중복 미포함)",
            "",
        ]
        for corpus, n in sorted(report.same_corpus_internal_duplicate_groups.items()):
            lines.append(
                f"- `{corpus}`: {n}그룹 (동일 스켈레톤의 단답형/객관식 트윈 — §5.2와 동일 패턴)"
            )
    if report.parse_errors:
        lines += ["", "### 6.2 파싱 실패 상세", ""]
        for err in report.parse_errors:
            lines.append(f"- `{err.corpus}` line {err.line_no}: {err.error_type} — {err.detail}")

    # ── 7. QUAL-03 — 재서술 무변화 직접 측정 ──
    noop = report.rephrase_noop
    lines += [
        "",
        f"## 7. QUAL-03 — 재서술(rephrase) 무변화 직접 측정 (대상: `{noop.target_corpus}`)",
        "",
        "> QUAL-01(§2.2·§5.2·§6.1)의 lineage 배제 쌍(간접 신호)은 원본이 *다른 코퍼스*에 있고 "
        "텍스트가 교차매칭될 때만 포착되는 **하한값**이다. 이 절은 대상 코퍼스 전량을 순회하며 "
        "`relations[0].parent_slug`로 선언된 원본을 전 코퍼스에서 직접 찾아 정규화 텍스트를 "
        "대조하는 **전수 직접 측정**이다(`normalize_question_text`와 동등 기준 — "
        "`l3/equivalent/rephrase_hygiene._normalize_for_comparison`).",
    ]
    if noop.total == 0:
        lines += ["", f"- 대상 코퍼스 `{noop.target_corpus}`가 이번 스캔에 없어 측정 불가."]
    else:
        rate_text = (
            f"{noop.unchanged_rate * 100:.1f}%"
            if noop.unchanged_rate is not None
            else "산출불가(측정 가능 모집단 0)"
        )
        lines += [
            "",
            f"- 전량: **{noop.total}**건",
            "",
            "| 판정 | 건수 | 비고 |",
            "|---|---:|---|",
            f"| 무변화(원본과 정규화 텍스트 완전 일치) | {noop.unchanged_count} | 재서술이 발문을 "
            "바꾸지 않음 |",
            f"| 정상변화 | {noop.changed_count} | 발문이 실제로 다양화됨 |",
            f"| 부모 미선언(`relations` 없음) | {noop.no_parent_declared_count} | 측정 불가 — "
            "분모(무변화+정상변화)에서 제외 |",
            f"| 고아 참조(`parent_slug`가 전 코퍼스 어디에도 없음) | {noop.orphan_parent_count} "
            "| 측정 불가 — 분모에서 제외 |",
            f"| **무변화 비율(측정 가능 모집단 기준)** | **{rate_text}** | 분모 = "
            f"{noop.measurable_count}건 |",
        ]
        if report.lineage_excluded_pair_count == noop.unchanged_count:
            comparison = (
                f"QUAL-01 간접 하한(`lineage_excluded_pair_count`): "
                f"**{report.lineage_excluded_pair_count}**쌍 — 이번 직접 측정 무변화 "
                f"**{noop.unchanged_count}**건과 **정확히 일치**한다. 이 코퍼스 상태에서는 "
                "간접 하한이 우연이 아니라 **타이트한 하한**이었다는 뜻이다 — "
                "`generated_v0`↔`rephrased_v0` 관계가 전부 1:1이고 부모가 항상 (다른 코퍼스인) "
                "`generated_v0`에 있어, QUAL-01의 교차코퍼스 매칭이 이 축의 모든 사례를 이미 "
                "놓치지 않고 포착했기 때문이다."
            )
        else:
            comparison = (
                f"QUAL-01 간접 하한(`lineage_excluded_pair_count`): "
                f"**{report.lineage_excluded_pair_count}**쌍 vs 이번 직접 측정 무변화 "
                f"**{noop.unchanged_count}**건 — **"
                f"{abs(report.lineage_excluded_pair_count - noop.unchanged_count)}건 차이**. "
                "간접 신호가 실제보다 과소측정(진짜 하한)이었다는 뜻이다."
            )
        lines += ["", f"- {comparison}"]

        lines += ["", "### 7.1 처리 방침 권고", ""]
        if noop.measurable_count == 0:
            lines.append("- 측정 가능 모집단이 0건이라 방침을 판단할 근거가 없다.")
        else:
            rate = noop.unchanged_rate or 0.0
            if rate >= 0.5:
                lines += [
                    f"무변화 비율 **{rate * 100:.1f}%**는 과반이다 — 개별 레코드의 우연한 결함이 "
                    "아니라 **재서술 생성 파이프라인의 구조적 특성**으로 판단한다.",
                    "",
                    "**근거**: `problem_corpus_rephrase.run_corpus_rephrase`는 "
                    "`QuestionRephraser.rephrase()`가 **어떤 사유로 실패하든**(수식 추출 실패· "
                    "provider 예외·수치 불변 위반·위생 위반·무변화 전부 포함) fail-closed로 "
                    "원본 텍스트를 그대로 레코드에 써서 코퍼스에 편입시킨다 — `outcome.rephrased`"
                    "/`reason_code`는 리포트의 표본 10건에만 남고 **레코드 자체에는 저장되지 "
                    "않는다**. 이번 태스크가 확장한 위생 게이트(`rephrase.classify_invariance_"
                    "failure`에 `original_text` 배선 — rephrase_hygiene ⑦축)는 *신규* 생성 시 "
                    "LLM이 실제로 만들어낸 원문-근접 출력을 정규화 비교로 더 정밀하게 잡아내는 "
                    "데는 유효하지만(결함주입 테스트로 실측 확인), *이미 다른 사유로 "
                    "fail-closed된* 레코드가 코퍼스에 편입되는 것 자체는 막지 못한다 — "
                    "`run_corpus_rephrase`에는 애초에 '드롭'이라는 선택지가 없기 때문이다.",
                    "",
                    "**권고**:",
                    f"1. 기존 {noop.total}건 중 무변화 {noop.unchanged_count}건은 **개별 "
                    "재생성이 아니라 파이프라인 재검토**(수식 추출 실패율·provider 성공률·검증 "
                    "통과율의 근본 원인 진단) 후 일괄 재실행 대상이다 — 콘텐츠 생성 비용 판단이 "
                    "필요해 이 태스크 범위 밖이며 별도 태스크로 분리 권장.",
                    "2. 재발 방지에는 이번 위생 게이트 확장(②) 외에 `run_corpus_rephrase`가 "
                    "`outcome.rephrased=False`인 레코드를 코퍼스에서 제외하거나 최소한 "
                    "`rephrase_status` 필드로 영속화하는 별도 설계 변경이 필요하다(이것도 이 "
                    "태스크 범위 밖 — 정직한 잔여).",
                ]
            else:
                lines.append(
                    f"- 무변화 비율 **{rate * 100:.1f}%**는 과반 미만이다 — 파이프라인 전면 "
                    "재검토보다 개별 레코드 단위 재생성/은퇴 검토가 비용 대비 합리적일 수 있다. "
                    "최종 실행 여부는 오케스트레이터/Kiki가 이 측정치를 보고 결정한다."
                )

    lines.append("")
    return "\n".join(lines)


def report_to_json(report: DuplicationReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "total_problems": report.total_problems,
        "corpora": [
            {
                "name": ld.name,
                "status": ld.status,
                "problems": len(ld.records),
                "parse_errors": len(ld.parse_errors),
            }
            for ld in report.corpora
        ],
        "t1_slug_collision": {
            "baseline_count": _T1_BASELINE_COUNT,
            "baseline_source": _T1_BASELINE_SOURCE,
            "current_count": len(report.slug_collisions),
            "corpus_pairs_scanned": report.corpus_pairs_scanned,
            "pair_counts": [
                {"corpus_a": a, "corpus_b": b, "collisions": n}
                for (a, b), n in sorted(report.slug_collision_pair_counts.items())
            ],
            "collisions": [
                {"corpus_a": c.corpus_a, "corpus_b": c.corpus_b, "slug": c.slug}
                for c in report.slug_collisions
            ],
        },
        "t2_real_duplicates": {
            "criteria": [
                "(a) 서로 다른 코퍼스 파일 소속",
                "(b) 정규화된 question_text 완전 일치",
                "(c) relations 계보 그래프상 같은 연결요소(정당한 형제)가 아님",
            ],
            "lineage_graph": {
                "node_count": report.lineage_node_count,
                "edge_count": report.lineage_edge_count,
            },
            "raw_cross_corpus_candidates": report.cross_corpus_text_match_candidates,
            "lineage_excluded_count": report.lineage_excluded_pair_count,
            "confirmed_count": report.duplicate_pair_count,
            "confirmed_same_format_count": len(report.duplicate_pairs_same_format),
            "confirmed_diff_format_count": len(report.duplicate_pairs_diff_format),
            "pairs": [
                {
                    "corpus_a": p.corpus_a,
                    "slug_a": p.slug_a,
                    "question_format_a": p.question_format_a,
                    "corpus_b": p.corpus_b,
                    "slug_b": p.slug_b,
                    "question_format_b": p.question_format_b,
                    "normalized_text": p.normalized_text,
                    "same_question_format": p.same_question_format,
                    "demo_pool_co_exposed": p.demo_pool_co_exposed,
                }
                for p in report.duplicate_pairs
            ],
            "same_corpus_internal_duplicate_groups": report.same_corpus_internal_duplicate_groups,
        },
        "t3_verify_conditions_signature": {
            "computed": False,
            "note": _T3_NOTE,
        },
        "qual03_rephrase_noop_direct_measurement": {
            "target_corpus": report.rephrase_noop.target_corpus,
            "total": report.rephrase_noop.total,
            "unchanged_count": report.rephrase_noop.unchanged_count,
            "changed_count": report.rephrase_noop.changed_count,
            "no_parent_declared_count": report.rephrase_noop.no_parent_declared_count,
            "orphan_parent_count": report.rephrase_noop.orphan_parent_count,
            "measurable_count": report.rephrase_noop.measurable_count,
            "unchanged_rate": report.rephrase_noop.unchanged_rate,
            "qual01_indirect_lineage_excluded_pair_count": report.lineage_excluded_pair_count,
        },
        "demo_pool": {
            "status": report.demo_pool_status,
            "corpora": sorted(report.demo_pool_corpora),
            "co_exposed_duplicate_pair_count": len(report.demo_co_exposed_pairs),
        },
        "honest_accounting": {
            "parse_error_lines": len(report.parse_errors),
            "records_without_slug": report.records_without_slug,
            "records_without_question_text": report.records_without_question_text,
            "internal_duplicate_slug_total": report.internal_duplicate_slug_total,
            "parse_errors": [
                {
                    "corpus": e.corpus,
                    "line_no": e.line_no,
                    "error_type": e.error_type,
                    "detail": e.detail,
                }
                for e in report.parse_errors
            ],
        },
    }


def dump_json(report: DuplicationReport) -> str:
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
    """CLI 엔트리 — 중복 감사 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    실중복이 몇 쌍이 나오든 exit 0이다 — 게이트가 아니라 관측이기 때문
    (`problem_bank_coverage`와 동일 원칙). exit 2는 *관측 자체가 불가능한* 입력 오류(지정
    코퍼스 부재·코퍼스 루트 자체가 비어 있음)에만 쓴다. 데모 시드 스크립트 부재는 경고만
    (보조 축 — `problem_bank_coverage`의 유형 카탈로그 부재 처리와 동일 관례).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_duplication_audit",
        description=(
            "문항 코퍼스 중복 감사(QUAL-01) — T1 슬러그 충돌·T2 실중복(계보 배제)·T3 비-기준"
            "(문서화만). 결정론·게이트 아님(exit 0/2)."
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
        "--seed-demo-path",
        type=Path,
        default=_DEFAULT_SEED_DEMO_PATH,
        help=f"데모 시드 스크립트 경로(기본 {_DEFAULT_SEED_DEMO_PATH}).",
    )
    parser.add_argument(
        "--max-listed",
        type=int,
        default=60,
        help="본문에 나열할 실중복 쌍 최대 개수(형식별 각각·기본 60·전량은 --json).",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=None,
        help="JSON 산출물 경로(선택·미지정이면 stdout 마크다운만).",
    )
    args = parser.parse_args(argv)

    loads, problems = _resolve_loads(args.corpus_root, args.corpus)

    demo_pool: frozenset[str]
    demo_status: DemoPoolStatus
    if args.seed_demo_path.is_file():
        demo_pool = demo_pool_corpora(args.seed_demo_path)
        demo_status = "파일확인됨"
        if not demo_pool:
            print(
                f"경고 — {args.seed_demo_path}에서 _CORPORA 패턴 매치 0건(정규식이 스크립트 "
                "구현과 어긋났을 수 있다) — 데모풀 동시노출 축은 전부 False로 표시됩니다.",
                file=sys.stderr,
            )
    else:
        demo_pool = frozenset()
        demo_status = "파일없음"
        print(
            f"경고 — 데모 시드 스크립트 없음({args.seed_demo_path}) — 데모풀 동시노출 축은 "
            "관측 불가로 표시됩니다.",
            file=sys.stderr,
        )

    report = build_report(loads, demo_pool=demo_pool, demo_pool_status=demo_status)
    print(render_report(report, max_listed=args.max_listed))
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
