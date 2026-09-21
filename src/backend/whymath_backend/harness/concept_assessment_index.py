"""개념 평가 재료 참조 인덱스 빌더 + 렌더 성공률 리포트 CLI (LLM 0·DB 0·HTTP 0·결정론).

정본: `docs/architecture/ai_content_generation_gap_review.md` §3 D2. 숙달(R4) 판정 학생이 받는
`/study` 404를 해소하는 슬라이스의 *빌드타임* 쪽이다.

두 일을 한다:

  ① **참조 인덱스 빌드** — 검증 통과 문항의 `verify{conditions, answer_map}`를 개념 태그로 이어
     `data/corpus/concept_assessment_v1/index.json`에 남긴다(`--write`). 신규 저작 0·LLM 0 —
     검증 앵커는 원천 문항에서 *상속*한다(런타임 소비는 `l3/render/assessment_bank.py`).
  ② **렌더 성공률 리포트** — 개념 코퍼스 437행을 실제 어댑터 5종에 통과시켜 **주입 전 / 주입 후**
     성공률을 어댑터별로 낸다. 주입 전 PROBLEM_BASED가 0%임을 *실제로 재현*하고 주입 후를
     측정하므로, 두 값이 같으면 측정 자체가 무효라는 것이 리포트에 드러난다(변별력).

**미커버 정직 기록**: 참조 주입에 실패한 개념(해당 검증 통과 문항 미보유)은 카운트와 code 목록으로
산출물·리포트에 *명시*한다 — 커버된 것만 세는 침묵 통과를 구조적으로 막는다.

**게이트가 아니다(기본)**: 커버율이 낮아도 exit 1을 내지 않는다(`problem_bank_coverage` 동형 —
관측 도구를 CI 빨간불로 만들면 저작 우선순위 입력이라는 용도가 파괴된다). 다만 회귀 방어용으로
`--min-problem-based-rate`를 주면 그 임계 미달 시 exit 1을 낸다(옵트인 게이트).

"검증 통과"의 정의는 **추측하지 않고 저장소 정본을 재사용**한다 —
`harness/corpus_reverify._reverify_one`(Tier1+근선택+Tier2+개념형 디스패치)이 'pass'를 낸 문항만
후보다. 그 위에 겹을 더 얹는다:
  · `answer_map` 비어 있지 않음 — `ConceptAssessment`의 불변식(빈 검증의 통과 위장 금지).
  · `verify_answer(conditions, answer_map)`가 pass — 렌더 시점에 어댑터가 *정확히 이 호출*을 하므로
    (`l3/render/adapters._assessment_signal`), 여기서 통과하지 못하는 재료를 넣으면 런타임에
    RENDER_UNVERIFIED로 미끄러진다. 근 집계(Vieta)·개념형(개수/판정) 문항이 이 겹에서 걸린다.
  · 저작권 위생 — `source_type=자체생성` + `license=WHYMATH_GENERATED`만(타 출처 본문 상속 금지).
  · **검수 통과** — `review_status == approved`만(아래 참조).
각 겹에서 몇 건이 탈락했는지 리포트에 남긴다(필터가 살아 있는지 관측 가능).

────────────────────────────────────────────────────────────────────────────
검수 축(CONT-01) — 판정 권위를 L6와 공유하는 방식
────────────────────────────────────────────────────────────────────────────
`PB-03`은 검수를 **fail-closed 노출 게이트**로 만들어 L6 6모드·`l6/blueprint/assembly.py`·기본
CAT(`api/me.py`)에 배선했다. 그런데 `S3-26`이 만든 *두 번째* 학생 노출 경로(`/study`의 개념 평가
재료 주입)는 이 인덱스를 경유하므로, 이 필터에 검수 축이 없으면 **같은 문항이 L6에서는 차단되고
/study에서는 통과**하는 비대칭이 생긴다(정본화≠집행 계열의 재발형). 그래서 여기에 같은 축을 건다.

**판정 권위 단일화 — 채택한 방법과 근거**: `l6/_shared.is_review_cleared`는 `Problem`(pydantic)
인스턴스를 받는데 이쪽 입력은 빌드타임 JSONL dict라 그 함수를 직접 재사용할 수 없다. dict를
`Problem`으로 구성해 부르는 방법도 있으나, 코퍼스 2,600여 행마다 전체 검증기를 태우는 비용과
*이 도구가 문항 스키마 전체에 결합*되는 부작용을 산다. 따라서 **판정 헬퍼를 값 수준으로 승격**해
공유한다 — `schema/enums.py::is_review_status_cleared`(L1)가 "어떤 값이 검수 통과인가"의 유일한
정의이고, `is_review_cleared`는 그 위의 `Problem` 어댑터, 이 모듈은 dict 값을 그대로 넘긴다.
문자열 리터럴 `"approved"`를 이 파일에 새로 적지 않는다(기준 이원화 금지).

**합치지 않는 두 축**: 저작권 위생(법적 축, `is_exposable` 대응)과 검수(운영 축)는 PB-03이
의도적으로 분리한 설계다. 여기서도 **각각 독립된 `if`·독립된 drop 사유**로 둔다 — 합치면 운영
사유로 법적 게이트를 느슨하게 하는 압력이 생기고, 리포트에서 어느 축이 걸렀는지도 사라진다.

7계층 메모: 이 모듈은 `schema.enums`(L1의 순수 enum 모듈 — `from enum import Enum` 외 의존 0)만
추가로 import한다. **ORM·세션·L6를 import하지 않는다** — 런타임 소비처
(`l3/render/assessment_bank.py`)의 "DB·ORM·LLM·네트워크 미접촉" 계약과 같은 자세를 유지한다.

사용:
    python -m whymath_backend.harness.concept_assessment_index                    # 리포트만
    python -m whymath_backend.harness.concept_assessment_index --write            # 산출물 갱신
    python -m whymath_backend.harness.concept_assessment_index --json out/r.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# EOS-89: 이 모듈은 **INFRA 측정 CLI**(엔트리포인트)라 합성 루트를 직접 소비한다 — Core에서
# 걷어낸 pull 지점과 구분되는 자리다(계획서 100 §3.8 · 경계 문서 §9.2 "엔트리포인트 소비").
from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.harness.corpus_reverify import _reverify_one
from whymath_backend.l3.render.adapter import RenderContext
from whymath_backend.l3.render.dsl import ConceptAssessment, ConceptDSL, from_concept_content
from whymath_backend.l3.render.registry import get_adapter, registered_strategies
from whymath_backend.l3.verify_answer import verify_answer
from whymath_backend.l4.content_supply import SupplyTally

# 검수 판정의 단일 권위(CONT-01) — `l6/_shared.is_review_cleared`가 같은 함수를 쓴다.
# 문자열 "approved"를 이 파일에 다시 적지 않기 위한 import다(기준 이원화 금지).
from whymath_backend.schema.enums import is_review_status_cleared
from whymath_backend.schema.verification_capabilities import (
    AssessmentAnswerVerifier,
    ExpressionSeal,
)

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(다른 harness 모듈과 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
DEFAULT_CONCEPT_PATH = DEFAULT_CORPUS_ROOT / "concept_content_v1" / "content.json"
DEFAULT_INDEX_DIR = DEFAULT_CORPUS_ROOT / "concept_assessment_v1"

# 문제 코퍼스 관례(`problem_bank_coverage`와 동일 글롭).
CORPUS_DIR_GLOB = "problem_bank*"
CORPUS_FILE_NAME = "problems.jsonl"

# 저작권 위생 — 상속 허용 출처(자체 저작만). 이 두 값이 아니면 재료를 상속하지 않는다.
OWN_SOURCE_TYPE = "자체생성"
OWN_LICENSE = "WHYMATH_GENERATED"

# 매칭 축 — 우선순위 순(작은 값이 이긴다). 신규 분류축이 아니라 *기존 코퍼스 태그 이름*이다.
AXIS_CONCEPT_SRC_ID = "concept_src_id"
"""문항 `concepts[].concept_src_id`가 개념 code와 직접 일치(가장 강한 신호)."""

AXIS_STANDARD_CODE = "standard_code"
"""문항 `achievement_standard_codes` ∩ 개념 `standard_codes`(성취기준 다리)."""

_AXIS_PRIORITY: dict[str, int] = {AXIS_CONCEPT_SRC_ID: 0, AXIS_STANDARD_CODE: 1}

# 탈락 사유 — 필터가 실제로 무엇을 걸렀는지 리포트에 드러내기 위한 집계 키.
DROP_NOT_OWN_LICENSE = "NOT_OWN_LICENSE"
DROP_NOT_REVIEW_CLEARED = "NOT_REVIEW_CLEARED"
"""검수 미통과(`review_status != approved`) — 저작권 축과 **별개 키**다(CONT-01).

법적 축(`NOT_OWN_LICENSE`)과 한 키로 묶지 않는 이유: 묶으면 리포트에서 "저작권 때문에 빠졌다"와
"검수 대기라 빠졌다"가 구분되지 않아, 검수 백필로 해소될 건과 영구 차단 건이 같은 숫자에 섞인다.
"""

DROP_REVERIFY_NOT_PASS = "REVERIFY_NOT_PASS"
DROP_EMPTY_ANSWER_MAP = "EMPTY_ANSWER_MAP"
DROP_TIER1_NOT_PASS = "TIER1_NOT_PASS"


# ──────────────────────────────────────────────────────────────────────────
# 입력 로드
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ConceptRow:
    """개념 코퍼스 1행의 렌더 투영 입력 — `ConceptContent` ORM 행과 *속성 이름이 같다*.

    `from_concept_content(row)`가 `Any`를 받고 속성만 읽으므로(db-free 불변식), 이 값객체를 그대로
    넘겨 실제 렌더 경로를 재현할 수 있다 — 리포트가 "코퍼스에서 렌더까지"를 진짜로 통과시킨다.

    ⚠️ **이름 충돌 주의(CONT-01)**: 아래 `review_status`는 *개념 콘텐츠 코퍼스*의 축이고 실측 값은
    전 행 `ai_estimated`다. CONT-01이 건 검수 게이트가 보는 것은 이 축이 **아니라** *문항 코퍼스*의
    `review_status`(`ReviewStatus` enum — pending/approved/rejected)이며, 그 판정은
    `eligible_problem_refs`에서 문항 레코드에 대해 이뤄진다. 이름이 같고 값집합이 달라 혼동하기
    쉬우므로, 개념 축을 문항 검수 게이트로 오용하지 않는다(값집합이 애초에 겹치지 않아 그렇게 하면
    전 개념이 fail-closed로 사라진다).
    """

    code: str
    name: str
    subject: str
    unit: str | None
    metaphor: str | None
    misconception: str | None
    formal_definition_internal: str | None
    accepted_expressions: str | None
    standard_codes: tuple[str, ...]
    atom_codes: tuple[str, ...] = ()
    review_status: str | None = None
    # 렌더 투영 입력은 아니다(`l3/render/dsl`이 의도적으로 매핑하지 않는 필드) — 코퍼스 감사
    # (`harness/concept_content_audit`)가 크롤링 잔류 오염을 전수 스캔할 수 있게 적재만 한다.
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class ProblemRef:
    """상속 후보 문항 1건 — 참조 키(slug·뱅크)와 검증 앵커(conditions·answer_map)."""

    slug: str
    bank: str
    unit_codes: tuple[str, ...]
    standard_codes: tuple[str, ...]
    concept_src_ids: tuple[str, ...]
    conditions: tuple[str, ...]
    answer_map: dict[str, str]
    prompt: str | None
    difficulty: float | None

    def to_assessment(self) -> ConceptAssessment:
        """참조 → 렌더 입력(`ConceptAssessment`). 값 복제가 아니라 원천 재료의 *상속*이다."""
        return ConceptAssessment(
            conditions=self.conditions,
            answer_map=dict(self.answer_map),
            prompt=self.prompt,
        )


def _opt_str(value: object) -> str | None:
    """빈 문자열·공백만·비-str → None(`from_concept_content._clean`과 같은 규약)."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def load_concepts(path: Path) -> list[ConceptRow]:
    """개념 콘텐츠 코퍼스 `content.json` → `ConceptRow` 목록(code 정렬·결정론).

    `l1/concept_content/projection.load_concept_content_from_json`과 같은 관용 파싱이다(필수 3필드
    누락 행은 건너뛴다). 적재기를 재사용하지 않고 여기서 다시 읽는 이유는 그 모듈이 sync 엔진
    빌더·`Settings` 해석을 함께 끌고 오기 때문이다 — 이 도구는 파일만 읽고 DB에 접속하지 않는다
    (`SupplyTally` 재사용 때문에 ORM 패키지가 import 경로에 들어오지만 세션·연결은 만들지 않는다).

    Raises:
        FileNotFoundError: 코퍼스 부재(조용히 빈 목록으로 위장하지 않는다).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[ConceptRow] = []
    for record in payload.get("content", []):
        code = _opt_str(record.get("code"))
        name = _opt_str(record.get("name"))
        subject = _opt_str(record.get("subject"))
        if code is None or name is None or subject is None:
            continue
        raw_codes = record.get("standard_codes")
        rows.append(
            ConceptRow(
                code=code,
                name=name,
                subject=subject,
                unit=_opt_str(record.get("unit")),
                metaphor=_opt_str(record.get("metaphor")),
                misconception=_opt_str(record.get("misconception")),
                formal_definition_internal=_opt_str(record.get("formal_definition_internal")),
                accepted_expressions=_opt_str(record.get("accepted_expressions")),
                standard_codes=(
                    tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
                ),
                review_status=_opt_str(record.get("review_status")),
                explanation=_opt_str(record.get("explanation")),
            )
        )
    rows.sort(key=lambda r: r.code)
    return rows


def discover_problem_files(corpus_root: Path) -> list[Path]:
    """`problem_bank*/problems.jsonl` 목록(정렬 — 결정론)."""
    return sorted(
        path / CORPUS_FILE_NAME
        for path in sorted(corpus_root.glob(CORPUS_DIR_GLOB))
        if (path / CORPUS_FILE_NAME).is_file()
    )


def _normalize_conditions(raw: object) -> tuple[str, ...]:
    """`verify.conditions`(str | list) → 튜플 정규화. 빈 조건은 빈 튜플(후보 탈락)."""
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(c).strip() for c in raw if str(c).strip())
    return ()


def eligible_problem_refs(
    files: list[Path],
) -> tuple[list[ProblemRef], Counter[str], int]:
    """문항 코퍼스 전수 → 상속 가능 후보 목록 + 탈락 사유 집계 + 총 스캔 건수.

    필터는 5겹이며 각 겹의 탈락 수를 돌려준다 — "필터가 0건을 걸렀다"와 "필터가 없다"를 구분할 수
    있어야 회귀를 본다. 겹 순서는 비용 순이다(문자열 비교 → 재검증 → SymPy).

    앞의 두 겹(저작권·검수)은 L6 노출 경로의 `is_exposable` / `is_review_cleared` 두 게이트와
    *같은 순서·같은 독립성*으로 놓았다(CONT-01) — 두 노출 경로가 같은 모양을 갖게 해, 한쪽에만
    축이 빠진 비대칭이 눈으로 보이게 하려는 배치다.
    """
    refs: list[ProblemRef] = []
    # 다섯 겹 전부를 0으로 미리 세운다 — "0건 걸렀다"와 "그 필터가 없다"를 리포트에서 구분하기
    # 위해서다(Counter는 미등장 키를 아예 출력하지 않아 필터 소실이 침묵으로 보인다).
    drops: Counter[str] = Counter(
        {
            DROP_NOT_OWN_LICENSE: 0,
            DROP_NOT_REVIEW_CLEARED: 0,
            DROP_REVERIFY_NOT_PASS: 0,
            DROP_EMPTY_ANSWER_MAP: 0,
            DROP_TIER1_NOT_PASS: 0,
        }
    )
    scanned = 0
    for path in files:
        bank = path.parent.name
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            record: dict[str, Any] = json.loads(stripped)
            scanned += 1

            # ① 저작권 위생 — 자체 저작만 상속(타 출처 본문 상속은 절대 금기).
            if record.get("source_type") != OWN_SOURCE_TYPE or record.get("license") != OWN_LICENSE:
                drops[DROP_NOT_OWN_LICENSE] += 1
                continue

            # ② 검수 통과 — 운영·정책 축(①의 법적 축과 **독립된 if**, PB-03 설계 유지).
            #    판정은 L6 노출 게이트와 같은 함수(`is_review_status_cleared`)가 한다 — 이 파일에
            #    "approved" 리터럴을 두지 않는다. fail-closed: 키 부재·None·pending·rejected 전부
            #    탈락. 값을 *정규화하지 않고* 그대로 넘긴다 — L6 런타임 게이트도 정규화 없이
            #    비교하므로, 여기서만 관대해지면(예: 공백 strip) 두 경로의 기준이 다시 갈린다.
            if not is_review_status_cleared(record.get("review_status")):
                drops[DROP_NOT_REVIEW_CLEARED] += 1
                continue

            # ③ 검증 통과 — 정의는 저장소 정본(`corpus_reverify`)을 그대로 재사용한다.
            state, _reason = _reverify_one(record, use_fuzz=False)
            if state != "pass":
                drops[DROP_REVERIFY_NOT_PASS] += 1
                continue

            verify = record.get("verify") or {}
            conditions = _normalize_conditions(verify.get("conditions"))
            answer_map = {str(k): str(v) for k, v in dict(verify.get("answer_map") or {}).items()}

            # ④ ConceptAssessment 불변식 — 빈 answer_map/조건은 검증 불가한 재료다.
            if not answer_map or not conditions:
                drops[DROP_EMPTY_ANSWER_MAP] += 1
                continue

            # ⑤ 렌더 시점과 *같은* 호출로 최종 확인 — 여기서 못 통과하면 런타임에
            #    RENDER_UNVERIFIED로 미끄러진다(근 집계·개념형 문항이 여기서 걸린다).
            if verify_answer(list(conditions), answer_map).state != "pass":
                drops[DROP_TIER1_NOT_PASS] += 1
                continue

            slug = _opt_str(record.get("slug")) or _opt_str(record.get("problem_id"))
            if slug is None:
                drops[DROP_EMPTY_ANSWER_MAP] += 1
                continue
            difficulty_raw = record.get("difficulty_overall")
            refs.append(
                ProblemRef(
                    slug=slug,
                    bank=bank,
                    unit_codes=tuple(str(c) for c in record.get("unit_codes") or ()),
                    standard_codes=tuple(
                        str(c) for c in record.get("achievement_standard_codes") or ()
                    ),
                    concept_src_ids=tuple(
                        str(c.get("concept_src_id"))
                        for c in record.get("concepts") or ()
                        if isinstance(c, dict) and c.get("concept_src_id")
                    ),
                    conditions=conditions,
                    answer_map=answer_map,
                    prompt=_opt_str(record.get("question_text")),
                    difficulty=(
                        float(difficulty_raw) if isinstance(difficulty_raw, (int, float)) else None
                    ),
                )
            )
    refs.sort(key=lambda r: (r.bank, r.slug))
    return refs, drops, scanned


# ──────────────────────────────────────────────────────────────────────────
# 매칭 (빌드타임 — 런타임에는 dict 조회만 남는다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class IndexEntry:
    """참조 인덱스 1행 — 개념 code와 상속 원천(문항)의 추적 가능한 연결."""

    concept_code: str
    concept_name: str
    problem_slug: str
    problem_bank: str
    problem_unit_codes: tuple[str, ...]
    match_axis: str
    matched_key: str
    conditions: tuple[str, ...]
    answer_map: dict[str, str]
    prompt: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "concept_code": self.concept_code,
            "concept_name": self.concept_name,
            "problem_slug": self.problem_slug,
            "problem_bank": self.problem_bank,
            "problem_unit_codes": list(self.problem_unit_codes),
            "match_axis": self.match_axis,
            "matched_key": self.matched_key,
            "conditions": list(self.conditions),
            "answer_map": dict(self.answer_map),
            "prompt": self.prompt,
        }

    def to_assessment(self) -> ConceptAssessment:
        return ConceptAssessment(
            conditions=self.conditions, answer_map=dict(self.answer_map), prompt=self.prompt
        )


def match_entries(
    concepts: list[ConceptRow], refs: list[ProblemRef]
) -> tuple[list[IndexEntry], list[str]]:
    """개념 × 후보 문항 매칭 → (인덱스 항목, 미커버 개념 code 목록). 결정론.

    한 개념에 여러 후보가 붙으면 **(축 우선순위 → 난이도 오름차순 → slug)**로 정렬해 첫 건만 쓴다.
    난이도를 오름차순으로 두는 이유는 교수학이다: PROBLEM_BASED는 개념 설명 *앞*에 문제를 세우므로,
    가장 쉬운 검증 통과 문항이 "생산적 고투"와 "좌절"의 경계에서 안전하다(정서 안전 우선). 개념당
    1건만 남겨 산출물이 (개념 × 문항)으로 자라지 않게 한다(조합폭발 방지).
    """
    by_src: dict[str, list[ProblemRef]] = {}
    by_standard: dict[str, list[ProblemRef]] = {}
    for ref in refs:
        for src_id in ref.concept_src_ids:
            by_src.setdefault(src_id, []).append(ref)
        for code in ref.standard_codes:
            by_standard.setdefault(code, []).append(ref)

    entries: list[IndexEntry] = []
    uncovered: list[str] = []
    for concept in concepts:
        candidates: list[tuple[int, float, str, str, ProblemRef]] = []
        for ref in by_src.get(concept.code, ()):
            candidates.append(
                (
                    _AXIS_PRIORITY[AXIS_CONCEPT_SRC_ID],
                    ref.difficulty if ref.difficulty is not None else 99.0,
                    ref.slug,
                    concept.code,
                    ref,
                )
            )
        for standard in concept.standard_codes:
            for ref in by_standard.get(standard, ()):
                candidates.append(
                    (
                        _AXIS_PRIORITY[AXIS_STANDARD_CODE],
                        ref.difficulty if ref.difficulty is not None else 99.0,
                        ref.slug,
                        standard,
                        ref,
                    )
                )
        if not candidates:
            uncovered.append(concept.code)
            continue
        priority, _difficulty, _slug, matched_key, best = min(
            candidates, key=lambda c: (c[0], c[1], c[2])
        )
        axis = AXIS_CONCEPT_SRC_ID if priority == 0 else AXIS_STANDARD_CODE
        entries.append(
            IndexEntry(
                concept_code=concept.code,
                concept_name=concept.name,
                problem_slug=best.slug,
                problem_bank=best.bank,
                problem_unit_codes=best.unit_codes,
                match_axis=axis,
                matched_key=matched_key,
                conditions=best.conditions,
                answer_map=best.answer_map,
                prompt=best.prompt,
            )
        )
    entries.sort(key=lambda e: e.concept_code)
    return entries, uncovered


# ──────────────────────────────────────────────────────────────────────────
# 렌더 성공률 (주입 전 / 주입 후 — 변별력의 핵심)
# ──────────────────────────────────────────────────────────────────────────
def _dsl_or_none(concept: ConceptRow) -> ConceptDSL | None:
    """개념 행 → 렌더 입력 DSL. 중립성 위반 등으로 투영이 거부되면 None(리포트가 별도 집계)."""
    try:
        return from_concept_content(concept)
    except ValueError:
        # pydantic ValidationError는 ValueError 하위 — 교수법-중립 위반·필수 필드 결측.
        return None


def render_rates(
    concepts: list[ConceptRow],
    entries: list[IndexEntry],
    *,
    seal: ExpressionSeal | None = None,
    assessment_verifier: AssessmentAnswerVerifier | None = None,
) -> tuple[dict[str, SupplyTally], dict[str, SupplyTally], int]:
    """어댑터별 렌더 성공률을 **주입 전 / 주입 후** 두 번 측정 → (before, after, dsl_invalid).

    집계 그릇은 `l4.content_supply.SupplyTally`를 *그대로* 쓴다 — 그 타입의 소비처가 리포트에도
    생겨 "generate로 집계되나 학생은 못 본" 이중 회계 왜곡이 관측 가능해진다(전략별 분해 포함).
    성공 판정은 `can_render`만이 아니라 **렌더 후 검증 통과**(`RenderedUnit.ok`)다 — 렌더가 되고도
    미검증이면 학생에게 나가지 않으므로 성공이 아니다.

    EOS-89: 어댑터는 이제 과목 능력 2종을 생성 시 주입받는다. 이 모듈은 **INFRA 측정 CLI**
    (프로세스가 여기서 시작한다 = 합성 루트를 소비해도 되는 자리)이므로 주입이 없으면 합성
    루트에서 기본 구현을 받아 온다. Core(`l3.render.*`·`l4.content_supply`)에는 그 폴백이
    없다 — 있으면 §3.8이 없애려던 pull 지점이 그대로 남는다.
    """
    inspector = seal if seal is not None else default_expression_seal()
    checker = (
        assessment_verifier
        if assessment_verifier is not None
        else default_assessment_answer_verifier()
    )
    by_code = {entry.concept_code: entry for entry in entries}
    strategies = sorted(registered_strategies(), key=lambda s: s.value)
    before: dict[str, SupplyTally] = {s.value: SupplyTally() for s in strategies}
    after: dict[str, SupplyTally] = {s.value: SupplyTally() for s in strategies}
    ctx = RenderContext()
    dsl_invalid = 0

    for concept in concepts:
        base = _dsl_or_none(concept)
        if base is None:
            dsl_invalid += 1
            continue
        entry = by_code.get(concept.code)
        injected = (
            base.model_copy(update={"assessment": entry.to_assessment()})
            if entry is not None
            else base
        )
        for strategy in strategies:
            adapter = get_adapter(strategy, seal=inspector, assessment_verifier=checker)
            for tally, dsl in ((before[strategy.value], base), (after[strategy.value], injected)):
                if not adapter.can_render(dsl):
                    tally.record(
                        "generate", strategy=strategy.value, fallback_reason="CANNOT_RENDER"
                    )
                    continue
                unit = adapter.render(dsl, ctx)
                if unit.ok:
                    tally.record("dsl_render", strategy=strategy.value)
                else:
                    tally.record(
                        "generate", strategy=strategy.value, fallback_reason="RENDER_UNVERIFIED"
                    )
    return before, after, dsl_invalid


# ──────────────────────────────────────────────────────────────────────────
# 리포트
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class IndexReport:
    """빌드 + 측정 결과 — 사람·자동화가 같은 숫자를 본다."""

    concepts_total: int
    problems_scanned: int
    problems_eligible: int
    drops: dict[str, int]
    entries: list[IndexEntry]
    uncovered: list[str]
    axis_counts: dict[str, int]
    unit_codes_attached: dict[str, int]
    unit_codes_orphan: dict[str, int]
    before: dict[str, SupplyTally] = field(default_factory=dict)
    after: dict[str, SupplyTally] = field(default_factory=dict)
    dsl_invalid: int = 0

    @property
    def covered(self) -> int:
        return len(self.entries)

    @property
    def coverage_rate(self) -> float | None:
        """개념 커버율(점추정). 개념 0이면 None — "미상"을 0%로 위장하지 않는다."""
        if self.concepts_total == 0:
            return None
        return self.covered / self.concepts_total

    def to_json(self) -> dict[str, Any]:
        return {
            "concepts_total": self.concepts_total,
            "concepts_covered": self.covered,
            "concepts_uncovered": len(self.uncovered),
            "coverage_rate": self.coverage_rate,
            "problems_scanned": self.problems_scanned,
            "problems_eligible": self.problems_eligible,
            "drops": dict(sorted(self.drops.items())),
            "match_axis_counts": dict(sorted(self.axis_counts.items())),
            "unit_codes_attached": dict(sorted(self.unit_codes_attached.items())),
            "unit_codes_orphan": dict(sorted(self.unit_codes_orphan.items())),
            "dsl_invalid": self.dsl_invalid,
            "render_rate_before": {k: v.to_json() for k, v in sorted(self.before.items())},
            "render_rate_after": {k: v.to_json() for k, v in sorted(self.after.items())},
            "uncovered_concept_codes": list(self.uncovered),
        }


def build_report(
    concepts: list[ConceptRow],
    refs: list[ProblemRef],
    drops: Counter[str],
    scanned: int,
) -> IndexReport:
    """매칭 + 렌더 성공률 측정을 묶어 리포트를 만든다(순수·결정론)."""
    entries, uncovered = match_entries(concepts, refs)
    axis_counts = Counter(entry.match_axis for entry in entries)
    attached_units: Counter[str] = Counter()
    for entry in entries:
        for unit_code in entry.problem_unit_codes:
            attached_units[unit_code] += 1
    # 고아 단원 코드 — 검증 통과 문항은 있는데 어느 개념에도 붙지 못한 단원(저작·태깅 공백 지목).
    orphan_units: Counter[str] = Counter()
    for ref in refs:
        for unit_code in ref.unit_codes:
            if unit_code not in attached_units:
                orphan_units[unit_code] += 1
    before, after, dsl_invalid = render_rates(concepts, entries)
    return IndexReport(
        concepts_total=len(concepts),
        problems_scanned=scanned,
        problems_eligible=len(refs),
        drops=dict(drops),
        entries=entries,
        uncovered=uncovered,
        axis_counts=dict(axis_counts),
        unit_codes_attached=dict(attached_units),
        unit_codes_orphan=dict(orphan_units),
        before=before,
        after=after,
        dsl_invalid=dsl_invalid,
    )


def _fmt_rate(value: float | None) -> str:
    """비율 표기 — None은 "미상"(0%로 위장하지 않는다)."""
    return "미상" if value is None else f"{value * 100:.1f}%"


def render_report(report: IndexReport, *, max_uncovered_listed: int = 20) -> str:
    """사람 가독 리포트 — 전/후 성공률·커버리지·미커버·탈락 사유."""
    lines = [
        "=" * 72,
        "개념 평가 재료 참조 인덱스 — 빌드 + 렌더 성공률 (LLM 0·신규 저작 0)",
        "=" * 72,
        f"개념 {report.concepts_total}  커버 {report.covered}  "
        f"미커버 {len(report.uncovered)}  커버율 {_fmt_rate(report.coverage_rate)}",
        f"문항 스캔 {report.problems_scanned}  상속 가능 {report.problems_eligible}",
        "[탈락 사유]",
    ]
    if report.drops:
        for reason, count in sorted(report.drops.items()):
            lines.append(f"  {reason}: {count}")
    else:
        lines.append("  (없음)")

    lines.append("[매칭 축]")
    if report.axis_counts:
        for axis, count in sorted(report.axis_counts.items()):
            lines.append(f"  {axis}: {count}")
    else:
        lines.append("  (없음)")

    lines.append("[어댑터별 렌더 성공률 — 주입 전 → 주입 후]")
    for strategy in sorted(report.after):
        rate_before = report.before[strategy].dsl_render_rate
        rate_after = report.after[strategy].dsl_render_rate
        lower_after = report.after[strategy].dsl_render_rate_lower
        moved = "" if rate_before == rate_after else "  ← 변화"
        lines.append(
            f"  {strategy:16s} {_fmt_rate(rate_before)} → {_fmt_rate(rate_after)}"
            f" (하한 {_fmt_rate(lower_after)}){moved}"
        )
    if report.dsl_invalid:
        lines.append(f"  * DSL 투영 거부(중립성 위반 등): {report.dsl_invalid}개념 — 측정 제외")

    lines.append(f"[미커버 개념 {len(report.uncovered)}개 — 해당 검증 통과 문항 미보유]")
    for code in report.uncovered[:max_uncovered_listed]:
        lines.append(f"  {code}")
    if len(report.uncovered) > max_uncovered_listed:
        lines.append(f"  … 외 {len(report.uncovered) - max_uncovered_listed}개")

    if report.unit_codes_orphan:
        lines.append(
            f"[고아 단원 코드 {len(report.unit_codes_orphan)}종 — 검증 통과 문항은 있으나 "
            "개념 연결 실패]"
        )
        for unit_code, count in sorted(
            report.unit_codes_orphan.items(), key=lambda kv: (-kv[1], kv[0])
        )[:10]:
            lines.append(f"  {unit_code}: {count}문항")
    lines.append("=" * 72)
    return "\n".join(lines)


def index_payload(report: IndexReport, *, concept_source: str) -> dict[str, Any]:
    """코퍼스 산출물 본문 — 런타임(`l3/render/assessment_bank.py`)이 읽는 계약.

    시각 필드를 넣지 않는다 — 같은 입력이면 같은 바이트가 나와야 재실행 diff가 *내용 변화*만
    보여준다(결정론·`_provenance.json`이 표지 메타를 담는다).
    """
    return {
        "source_citation": (
            "출처: 와이매스 자체작성 — 개념 평가 재료 *참조* 인덱스. 검증 통과 자체 저작 문항"
            "(problem_bank_*·source_type=자체생성·license=WHYMATH_GENERATED·review_status=approved)"
            "의 verify 앵커를 개념 태그로 이어 상속한 것이며, 신규 저작·LLM 생성은 0이다."
        ),
        "license_notice": (
            "WHYMATH_ORIGINAL — 원천 문항이 전량 자체 저작이므로 상속 재료도 자체 저작이다. "
            "검정교과서·평가원·EBS 본문은 원천 코퍼스에 애초에 없다(저작권 위생 필터가 "
            "source_type/license를 이중 확인한다)."
        ),
        "generated_by": "whymath_backend.harness.concept_assessment_index",
        "concept_source": concept_source,
        "index_version": 1,
        "counts": {
            "concepts_total": report.concepts_total,
            "concepts_covered": report.covered,
            "concepts_uncovered": len(report.uncovered),
            "problems_scanned": report.problems_scanned,
            "problems_eligible": report.problems_eligible,
        },
        # 자격 필터 5겹의 탈락 집계를 **산출물 자체에** 싣는다(CONT-01) — 리포트를 다시 돌리지
        # 않고도 "검수 축이 실제로 몇 건을 걸렀는가"가 감사 가능해야 하고, 어느 겹이 통째로
        # 사라지면(키 소실) 산출물 diff에서 바로 보인다. 값 전부 0이어도 키는 남는다.
        "filter_drops": dict(sorted(report.drops.items())),
        "entries": [entry.to_json() for entry in report.entries],
        "uncovered_concept_codes": list(report.uncovered),
    }


def write_index(report: IndexReport, *, out_dir: Path, concept_source: str) -> Path:
    """산출물 기록 — `index.json`. 디렉터리는 필요 시 만든다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.json"
    payload = index_payload(report, concept_source=concept_source)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI — 참조 인덱스 빌드(옵션) + 렌더 성공률 리포트."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.concept_assessment_index",
        description=(
            "검증 통과 문항의 verify 앵커를 개념 태그로 상속해 평가 재료 참조 인덱스를 만든다."
        ),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=DEFAULT_CORPUS_ROOT,
        help="코퍼스 루트(기본 data/corpus).",
    )
    parser.add_argument(
        "--concepts", type=Path, default=DEFAULT_CONCEPT_PATH, help="개념 콘텐츠 content.json 경로."
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_INDEX_DIR, help="산출물 디렉터리(--write 시)."
    )
    parser.add_argument("--write", action="store_true", help="산출물(index.json)을 기록한다.")
    parser.add_argument("--json", type=Path, default=None, help="리포트 JSON 저장 경로.")
    parser.add_argument(
        "--min-problem-based-rate",
        type=float,
        default=None,
        help="PROBLEM_BASED 주입 후 성공률 하한(옵트인 게이트 — 미달 시 exit 1).",
    )
    args = parser.parse_args(argv)

    try:
        concepts = load_concepts(args.concepts)
        files = discover_problem_files(args.corpus_root)
    except (OSError, ValueError) as exc:
        print(
            f"입력 오류 — error_type={type(exc).__name__} concepts={args.concepts} "
            f"corpus_root={args.corpus_root}",
            file=sys.stderr,
        )
        return _EXIT_INPUT_ERROR
    if not files:
        print(
            f"입력 오류 — 문제 코퍼스 없음: {args.corpus_root}/{CORPUS_DIR_GLOB}", file=sys.stderr
        )
        return _EXIT_INPUT_ERROR

    refs, drops, scanned = eligible_problem_refs(files)
    report = build_report(concepts, refs, drops, scanned)
    print(render_report(report))

    if args.write:
        # 산출물에는 **레포 상대경로**만 남긴다 — 절대경로를 박으면 빌드 머신 경로가 새고 같은
        # 입력이 머신마다 다른 바이트를 내 결정론이 깨진다.
        try:
            concept_source = str(args.concepts.resolve().relative_to(_REPO_ROOT))
        except ValueError:
            concept_source = args.concepts.name
        path = write_index(report, out_dir=args.out_dir, concept_source=concept_source)
        print(f"산출물 기록: {path}")
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"리포트 JSON: {args.json}")

    if args.min_problem_based_rate is not None:
        tally = report.after.get("PROBLEM_BASED")
        rate = tally.dsl_render_rate if tally is not None else None
        if rate is None or rate < args.min_problem_based_rate:
            print(
                f"게이트 실패 — PROBLEM_BASED 주입 후 성공률 {_fmt_rate(rate)} < "
                f"{_fmt_rate(args.min_problem_based_rate)}",
                file=sys.stderr,
            )
            return _EXIT_GATE_FAIL
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())


__all__ = [
    "AXIS_CONCEPT_SRC_ID",
    "AXIS_STANDARD_CODE",
    "DROP_EMPTY_ANSWER_MAP",
    "DROP_NOT_OWN_LICENSE",
    "DROP_NOT_REVIEW_CLEARED",
    "DROP_REVERIFY_NOT_PASS",
    "DROP_TIER1_NOT_PASS",
    "ConceptRow",
    "IndexEntry",
    "IndexReport",
    "ProblemRef",
    "build_report",
    "discover_problem_files",
    "eligible_problem_refs",
    "index_payload",
    "load_concepts",
    "main",
    "match_entries",
    "render_rates",
    "render_report",
    "write_index",
]
