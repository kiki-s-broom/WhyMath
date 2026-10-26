"""학습목표(Objective) 커버리지 관측 리포트 CLI — 빌드타임 결정론 관측(LLM 0·DB 0·HTTP 0).

설계 정본: `docs/architecture/curriculum_module_gap_review.md` §3 **D2**. `ARCH-18`(문제은행
커버리지 리포트, `harness/problem_bank_coverage.py`) 패턴을 그대로 재사용해, 성취기준 대장
전량(건수는 `docs/data/corpus_facts.md`의 `standards.k12`) 중 소단원(unit) DSL이 실제로
목표(Objective)로 분해한 건수·비율과 k_type(CONCEPT/PROCEDURE/REPRESENT/MODELING) 분포를 낸다.
`LearningObjective` 스키마·`unit_compiler.py` 컴파일러·런타임 API(`/v1/me/objectives/*`)는 이미
완비됐지만, 작성 당시 실데이터가 소단원 1건(`quadratic_maxmin`, 목표 4개)뿐이었다 — 그런 "완비된
소비 경로 + 미도달 공급원" 패턴을 드러내는 것이 이 도구의 존재 이유다(현재 소단원 수는
`units.count`, 커버 건수는 이 리포트의 출력).

**게이트가 아니다**(같은 harness 축의 `corpus_audit_eval`과의 결정적 차이): 커버율이 0.11%든
0%든 이 모듈은 **exit 1을 내지 않는다** — 종료 코드는 성공(0)과 입력 오류(2·성취기준 대장
부재/파싱 불가)만 구분한다. 목표 분해가 사람 검수가 필요한 교수학적 판단이라(CLAUDE.md
"구축 플레이북" 8대 원칙 위반 방지), "몇 건이 이미 됐고 몇 건이 남았는가"를 드러내는 *저작
우선순위 입력*일 뿐 승인/차단 판정이 아니다. **소단원 목표 분해 자동 생성 파이프라인은 이 모듈의
범위 밖**이다(`curriculum_module_gap_review.md` §5-⑥에 발화조건 기록 — 이 도구가 그 발화조건의
계측기다).

**커버리지 정의(주의 — `problem_bank_coverage`와 분모가 다르다)**: 성취기준 대장
(`standards.json`)의 `curriculum_revision` 값은 `"2022 개정"`처럼 "개정" 접미가 붙는 반면, 소단원
YAML의 `curriculum_rev`는 `"2022"`(접미 없는 연도)라 **문자열이 그대로 일치하지 않는다**. 이 값 형식
불일치를 여기서 해소하려 들지 않고(정규화 규칙을 날조하면 실측 없는 매핑이 된다), 애초에
`curriculum_rev`를 커버리지 분모/조인 키로 **쓰지 않는다** — 오직 `code`(대괄호 포함 고시코드)
문자열만으로 조인한다. 대신 분모는 대장 **레코드 전량(개정 통합 — 건수는 `standards.k12`)**으로
잡는다(레코드 1건 = 성취기준 고시 1개정 사본). 작성 당시 그 결과는 "895건 중 1건(0.11%)"이었다.
개정별 분포는 §1.2에서 대장 자체의 `curriculum_revision` 필드만으로(조인 없이) 별도로 보여준다 —
소단원의 `curriculum_rev`는 §3 유닛별 분해에 참고용 원문 그대로만 실리고 어떤 집계에도 쓰이지
않는다.

**정직 회계**(CLAUDE.md 침묵 실패 금지): 소단원 YAML 파싱 실패·필수 필드 누락·성취기준 대장에
없는 코드(오타·구버전 등)는 조용히 버리지 않고 전부 별도 카운트로 보고한다.

**결정론**: 난수 0·시각 의존 0·정렬 고정(코드/키는 사전순, 카운트류는 값 내림차순→키 오름차순).
같은 입력 파일 → 같은 바이트 출력(`--json` 산출물 포함).

사용:
    python -m whymath_backend.harness.objective_coverage
    python -m whymath_backend.harness.objective_coverage --json out/objective_coverage.json

계층 메모(CLAUDE.md 7계층): 코퍼스 JSON/YAML을 *읽기만* 하는 빌드타임 도구다. `db.models.
pedagogy_dsl.UnitSpec`(ORM)·`schema.unit_dsl.UnitDSL`(Pydantic)·`l1.pedagogy.unit_compiler`
어느 것도 import하지 않는다(hermetic) — 코퍼스 YAML 원본을 직접 파싱해 원본 문자열을 그대로
집계 키로 쓴다(`k_type` 값도 enum 검증 없이 코퍼스에 적힌 그대로 카운트).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

__all__ = [
    "CoverageReport",
    "ObjectiveRecord",
    "ParseError",
    "StandardEntry",
    "StandardsCatalog",
    "UnitRecord",
    "UnitsLoad",
    "build_report",
    "discover_unit_files",
    "load_standards",
    "load_units",
    "main",
    "parse_unit_yaml",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(problem_bank_coverage와 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
DEFAULT_STANDARDS_PATH = DEFAULT_CORPUS_ROOT / "standards_v1" / "standards.json"
DEFAULT_UNITS_ROOT = DEFAULT_CORPUS_ROOT / "units_v1"

# 소단원 DSL 파일 패턴 — `data/corpus/units_v1/*.unit.yaml`(`_provenance.json`은 매치하지 않음).
UNIT_FILE_GLOB = "*.unit.yaml"

RootStatus = Literal["적재됨", "비어있음", "데이터없음"]

UNTAGGED_UNIT_ID = "(unit_id 없음)"


# ──────────────────────────────────────────────────────────────────────────
# 입력 모델 — 성취기준 대장(순수 데이터·불변)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class StandardEntry:
    """NCIC 성취기준 1건(대장 투영·불변) — 같은 고시코드가 개정별로 별도 레코드로 존재할 수 있다."""

    norm_id: str
    code: str
    revision: str
    school_type: str
    subject: str
    domain: str
    sub_domain: str


@dataclass(slots=True, frozen=True)
class StandardsCatalog:
    """성취기준 대장(`data/corpus/standards_v1/standards.json`) 투영(불변).

    **분모는 항상 레코드 전량**(`record_count`)이다 — `problem_bank_coverage`와 달리 이 리포트는
    단일 개정으로 필터링하지 않는다(모듈 docstring "커버리지 정의" 참조). `unique_codes`는 조인·
    unknown 판정에만 쓰고, 분모로는 쓰지 않는다.
    """

    entries: tuple[StandardEntry, ...]

    @property
    def record_count(self) -> int:
        return len(self.entries)

    @property
    def unique_codes(self) -> frozenset[str]:
        return frozenset(e.code for e in self.entries)

    @property
    def revisions(self) -> tuple[str, ...]:
        return tuple(sorted({e.revision for e in self.entries}))


def load_standards(payload: object) -> StandardsCatalog:
    """성취기준 JSON(dict) → `StandardsCatalog`(순수).

    최상위가 dict가 아니거나 `standards` 배열이 없으면 ValueError로 즉시 실패한다 — 분모를 모른
    채 커버율을 내는 것은 관측이 아니라 날조이므로 조용한 폴백을 두지 않는다
    (`problem_bank_coverage.load_standards`와 동일 원칙).
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
                subject=str(item.get("subject") or ""),
                domain=str(item.get("domain") or ""),
                sub_domain=str(item.get("sub_domain") or ""),
            )
        )
    return StandardsCatalog(entries=tuple(entries))


# ──────────────────────────────────────────────────────────────────────────
# 입력 모델 — 소단원(unit) DSL YAML(순수 데이터·불변)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ParseError:
    """소단원 YAML 파일 1건의 파싱/타입 실패 — 조용히 버리지 않고 보고하기 위한 기록.

    `error_type`은 예외 타입명(CLAUDE.md "침묵 실패 금지"). 한 파일 = 한 소단원이라 파싱 실패는
    파일 단위로 격리한다(`problem_bank_coverage`의 라인 단위 격리와 동형 — 여기서의 "레코드"가
    파일이라는 점만 다르다).
    """

    unit_file: str
    error_type: str
    detail: str


@dataclass(slots=True, frozen=True)
class ObjectiveRecord:
    """소단원 1개 목표(Objective) — 커버리지 집계에 필요한 필드만 추린 투영(불변).

    `k_type`은 enum 검증 없이 YAML 원본 문자열 그대로 담는다(hermetic 원칙 — `schema.unit_dsl`을
    import하지 않는다). 값이 CONCEPT/PROCEDURE/REPRESENT/MODELING 밖이어도 조용히 버리지 않고
    그 문자열 그대로 집계에 드러낸다.
    """

    standard_code: str | None
    k_type: str | None


@dataclass(slots=True, frozen=True)
class UnitRecord:
    """소단원(`*.unit.yaml`) 1개 투영(불변). 정본 스키마는 `schema.unit_dsl.UnitDSL`이지만
    여기서는 pydantic 검증을 통과시키지 *않는다* — 이 도구의 목적이 "스키마 밖 값·누락"을
    정직하게 세는 것이기 때문이다(`problem_bank_coverage.ProblemRecord`와 동일 원칙).

    `curriculum_rev`는 참고용 원문(예: `"2022"`)일 뿐 어떤 조인·집계에도 쓰이지 않는다
    (모듈 docstring "커버리지 정의" 참조 — 대장의 `curriculum_revision`과 형식이 다르다).
    """

    file_name: str
    unit_id: str | None
    curriculum_rev: str | None
    standard_codes: tuple[str, ...]
    objectives: tuple[ObjectiveRecord, ...]


@dataclass(slots=True, frozen=True)
class UnitsLoad:
    """소단원 코퍼스(`data/corpus/units_v1/`) 적재 결과 전량 — 상태·유닛·파싱 실패(불변).

    `status`는 "데이터없음"(디렉터리 자체가 없음)과 "비어있음"(디렉터리는 있으나 `*.unit.yaml`
    파일 0건)을 구분한다. 어느 쪽도 **CLI 입력 오류가 아니다** — 소단원 0건은 이 리포트가 관측
    하려는 *현재 상태 그 자체*다(모듈 docstring 참조. `problem_bank_coverage`가 문제 코퍼스 0건을
    입력 오류로 보는 것과 의도적으로 다르다 — 그쪽은 코퍼스 부재가 이상 상태지만, 이쪽은 목표
    분해 0건이 실측된 정상 상태이기 때문).
    """

    root: Path
    status: RootStatus
    units: tuple[UnitRecord, ...]
    parse_errors: tuple[ParseError, ...]


def _str_list(value: object, field: str) -> tuple[str, ...]:
    """리스트[str] 필드 추출 — None/부재는 빈 튜플, 타입 위반은 TypeError(파일 단위 보고용)."""
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


def _opt_str(value: object, field: str) -> str | None:
    """문자열 필드 추출 — None/부재는 None, 타입 위반은 TypeError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}가 문자열이 아님(type={type(value).__name__})")
    return value


def parse_unit_yaml(text: str, *, unit_file: str) -> UnitRecord:
    """소단원 DSL YAML 문자열 → `UnitRecord`(순수). 실패는 예외로 올려 호출자가 파일 단위로 센다.

    `yaml.safe_load`만 쓴다(CLAUDE.md "임의 객체 역직렬화 금지·안전 로더"). `unit_id`는 누락돼도
    파일 전체를 버리지 않는다(표시용 라벨일 뿐 조인 키가 아니다) — 대신 `None`으로 두고 호출자가
    "unit_id 없음" 건수로 정직하게 센다. `standard_codes`·`objectives`는 타입이 잘못되면(리스트가
    아니거나 원소 타입 위반) 파일 전체를 파싱 실패로 처리한다(둘 다 커버리지 집계의 핵심 필드).
    """
    obj: object = yaml.safe_load(text)
    if not isinstance(obj, dict):
        raise TypeError(f"소단원 YAML 최상위가 object가 아님(type={type(obj).__name__})")

    unit_id = _opt_str(obj.get("unit_id"), "unit_id")
    curriculum_rev_raw = obj.get("curriculum_rev")
    curriculum_rev = str(curriculum_rev_raw) if curriculum_rev_raw is not None else None
    standard_codes = _str_list(obj.get("standard_codes"), "standard_codes")

    objectives_raw = obj.get("objectives")
    objectives: list[ObjectiveRecord] = []
    if objectives_raw is not None:
        if not isinstance(objectives_raw, list):
            raise TypeError(f"objectives가 배열이 아님(type={type(objectives_raw).__name__})")
        for idx, item in enumerate(objectives_raw):
            if not isinstance(item, dict):
                raise TypeError(f"objectives[{idx}]가 object가 아님(type={type(item).__name__})")
            objectives.append(
                ObjectiveRecord(
                    standard_code=_opt_str(
                        item.get("standard_code"), f"objectives[{idx}].standard_code"
                    ),
                    k_type=_opt_str(item.get("k_type"), f"objectives[{idx}].k_type"),
                )
            )

    return UnitRecord(
        file_name=unit_file,
        unit_id=unit_id,
        curriculum_rev=curriculum_rev,
        standard_codes=standard_codes,
        objectives=tuple(objectives),
    )


def discover_unit_files(units_root: Path) -> tuple[Path, ...]:
    """`data/corpus/units_v1/*.unit.yaml`을 파일명 오름차순으로 탐색(결정론)."""
    if not units_root.is_dir():
        return ()
    return tuple(sorted(units_root.glob(UNIT_FILE_GLOB), key=lambda p: p.name))


def load_units(units_root: Path) -> UnitsLoad:
    """소단원 코퍼스 디렉터리 → `UnitsLoad`(디렉터리 부재/빈 디렉터리도 예외 없이 상태로 표현).

    파일 단위 파싱 실패는 그 파일만 `parse_errors`에 적재하고 나머지 파일 집계는 계속한다 —
    관측 리포트라 부분 실패로 전체를 버리지 않되, 버린 파일 수를 반드시 표면화한다.
    """
    if not units_root.is_dir():
        return UnitsLoad(root=units_root, status="데이터없음", units=(), parse_errors=())
    paths = discover_unit_files(units_root)
    if not paths:
        return UnitsLoad(root=units_root, status="비어있음", units=(), parse_errors=())

    units: list[UnitRecord] = []
    errors: list[ParseError] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            units.append(parse_unit_yaml(text, unit_file=path.name))
        except Exception as exc:  # noqa: BLE001 — 파일 단위 격리·예외 타입명을 그대로 보고
            errors.append(
                ParseError(
                    unit_file=path.name, error_type=type(exc).__name__, detail=str(exc)[:200]
                )
            )
    return UnitsLoad(
        root=units_root, status="적재됨", units=tuple(units), parse_errors=tuple(errors)
    )


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 커버리지 리포트(순수 코어)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class CoverageReport:
    """커버리지 관측 결과 전량(불변·렌더/직렬화의 단일 입력).

    모든 dict는 렌더 시점에 정렬해 쓰므로 삽입 순서에 의존하지 않는다(결정론).
    """

    units_root: Path
    units_status: RootStatus
    units: tuple[UnitRecord, ...]
    unit_parse_errors: tuple[ParseError, ...]

    # 성취기준 축 — 분모는 항상 대장 레코드 전량(모듈 docstring "커버리지 정의").
    standards_record_count: int
    standards_unique_code_count: int
    standards_by_revision: dict[str, int]

    covered_codes: tuple[str, ...]  # 대장에 실재하고 어떤 unit에도 인용된 고유 코드(사전순).
    zero_coverage_codes: tuple[str, ...]  # 대장 고유 코드 중 어떤 unit도 인용 안 한 것(사전순).
    covered_record_count: int  # 커버된 코드에 해당하는 대장 *레코드* 수(개정 중복 포함).
    covered_entries: tuple[StandardEntry, ...]  # 커버된 레코드 상세(코드→개정 오름차순).

    coverage_by_revision: dict[str, tuple[int, int]]
    coverage_by_school_type: dict[str, tuple[int, int]]
    coverage_by_domain: dict[str, tuple[int, int]]

    unknown_standard_codes: dict[str, int]  # unit이 인용했으나 대장 어디에도 없는 코드→인용 횟수.

    # k_type 축.
    k_type_totals: dict[str, int]
    per_unit_k_type: dict[str, dict[str, int]]
    objectives_total: int

    # 정직 회계.
    units_missing_unit_id: int
    units_without_standard_codes: int
    objectives_without_standard_code: int
    objectives_without_k_type: int
    objective_code_outside_unit_list: int

    @property
    def coverage_rate(self) -> float | None:
        """분모(대장 레코드 전량)가 0이면 None — 가짜 0/1 금지."""
        if self.standards_record_count == 0:
            return None
        return self.covered_record_count / self.standards_record_count

    def sorted_units(self) -> tuple[str, ...]:
        """유닛 파일명 사전순(결정론) — §3 렌더 순서."""
        return tuple(sorted(u.file_name for u in self.units))


def build_report(units_load: UnitsLoad, catalog: StandardsCatalog) -> CoverageReport:
    """유닛 적재 결과 + 성취기준 대장 → `CoverageReport`(순수·부작용 0).

    커버 판정은 각 유닛의 **최상위 `standard_codes` 필드**(acceptance 원문 "UnitSpec.standard_
    codes에 걸린 건수")만으로 한다 — objective별 `standard_code`는 커버 판정에 쓰지 않고, 오직
    "자기 unit이 선언한 목록 밖 코드를 objective가 인용했는가"라는 별도 자기정합성 회계에만
    쓴다(§ CoverageReport.objective_code_outside_unit_list).
    """
    catalog_codes = catalog.unique_codes

    referenced: set[str] = set()
    unknown_citations: Counter[str] = Counter()
    k_type_totals: Counter[str] = Counter()
    per_unit_k_type: dict[str, Counter[str]] = {}
    objectives_total = 0
    units_missing_unit_id = 0
    units_without_standard_codes = 0
    objectives_without_standard_code = 0
    objectives_without_k_type = 0
    objective_code_outside_unit_list = 0

    for unit in units_load.units:
        per_unit_k_type.setdefault(unit.file_name, Counter())
        if unit.unit_id is None:
            units_missing_unit_id += 1
        if not unit.standard_codes:
            units_without_standard_codes += 1
        unit_code_set = set(unit.standard_codes)
        for code in unit.standard_codes:
            referenced.add(code)
            if code not in catalog_codes:
                unknown_citations[code] += 1
        for obj in unit.objectives:
            objectives_total += 1
            if obj.k_type:
                k_type_totals[obj.k_type] += 1
                per_unit_k_type[unit.file_name][obj.k_type] += 1
            else:
                objectives_without_k_type += 1
            if not obj.standard_code:
                objectives_without_standard_code += 1
            elif obj.standard_code not in unit_code_set:
                objective_code_outside_unit_list += 1

    covered_code_set = referenced & catalog_codes
    covered_codes = tuple(sorted(covered_code_set))
    zero_coverage_codes = tuple(sorted(catalog_codes - covered_code_set))
    covered_entries = tuple(
        sorted(
            (e for e in catalog.entries if e.code in covered_code_set),
            key=lambda e: (e.code, e.revision),
        )
    )
    covered_record_count = len(covered_entries)

    by_revision: dict[str, list[int]] = {}
    by_school: dict[str, list[int]] = {}
    by_domain: dict[str, list[int]] = {}
    for e in catalog.entries:
        for bucket, key in (
            (by_revision, e.revision),
            (by_school, e.school_type),
            (by_domain, e.domain),
        ):
            slot = bucket.setdefault(key or "(미상)", [0, 0])
            slot[1] += 1
            if e.code in covered_code_set:
                slot[0] += 1

    standards_by_revision: Counter[str] = Counter(e.revision for e in catalog.entries)

    return CoverageReport(
        units_root=units_load.root,
        units_status=units_load.status,
        units=units_load.units,
        unit_parse_errors=units_load.parse_errors,
        standards_record_count=catalog.record_count,
        standards_unique_code_count=len(catalog_codes),
        standards_by_revision=dict(standards_by_revision),
        covered_codes=covered_codes,
        zero_coverage_codes=zero_coverage_codes,
        covered_record_count=covered_record_count,
        covered_entries=covered_entries,
        coverage_by_revision={k: (v[0], v[1]) for k, v in by_revision.items()},
        coverage_by_school_type={k: (v[0], v[1]) for k, v in by_school.items()},
        coverage_by_domain={k: (v[0], v[1]) for k, v in by_domain.items()},
        unknown_standard_codes=dict(unknown_citations),
        k_type_totals=dict(k_type_totals),
        per_unit_k_type={name: dict(counts) for name, counts in per_unit_k_type.items()},
        objectives_total=objectives_total,
        units_missing_unit_id=units_missing_unit_id,
        units_without_standard_codes=units_without_standard_codes,
        objectives_without_standard_code=objectives_without_standard_code,
        objectives_without_k_type=objectives_without_k_type,
        objective_code_outside_unit_list=objective_code_outside_unit_list,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def _pct(numerator: int, denominator: int) -> str:
    """비율 렌더 — 분모 0은 '데이터없음'(0.0%로 위장 금지).

    이 리포트는 자릿수가 작은 비율(예: 0.11%)이 정상 상태라 소수점 둘째 자리까지 낸다
    (`problem_bank_coverage`의 첫째 자리 표기보다 정밀도를 한 자리 높임).
    """
    if denominator == 0:
        return "데이터없음"
    return f"{numerator / denominator * 100:.2f}%"


def _sorted_counts(counts: dict[str, int]) -> list[tuple[str, int]]:
    """카운트 정렬 — 값 내림차순 → 키 오름차순(결정론)."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _sorted_bucket(bucket: dict[str, tuple[int, int]]) -> list[tuple[str, tuple[int, int]]]:
    """커버 매트릭스(dict[key, (covered, total)]) 정렬 — 커버 내림차순→분모 내림차순→키 오름차순."""
    return sorted(bucket.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))


def render_report(report: CoverageReport, *, max_covered_display: int = 100) -> str:
    """커버리지 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음).

    거의 모든 성취기준이 0커버인 상태가 정상(작성 당시 894/895 — 현재 값은 리포트 출력)이라 **0커버
    코드를 전부 나열하지 않는다** — 대신 (작을 것으로 예상되는) *커버된* 코드 목록을 §1.1에 상세히
    싣는다. 커버된 목록이 `max_covered_display`를 넘기면 잘렸다는 사실을 문장으로 남긴다(조용한 절단
    금지·전량은 `--json` 산출물에 있다).
    """
    lines: list[str] = [
        "# 학습목표(Objective) 커버리지 관측 리포트 (CUR-02)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(커버율이 아무리 낮아도 실패시키지 않는다).",
        "> 정본: `docs/architecture/curriculum_module_gap_review.md` §3 D2. "
        "`ARCH-18`(`problem_bank_coverage.py`) 패턴 재사용.",
        "> 목표 분해 **자동 생성** 파이프라인은 범위 밖이다(§5-⑥ 발화조건 기록).",
        "",
        "## 0. 입력 요약",
        "",
        f"- 성취기준 대장: 레코드 **{report.standards_record_count}** · "
        f"고유 코드 **{report.standards_unique_code_count}** "
        f"(같은 고시코드가 개정별로 중복 등재 — 분모는 이 리포트에서 **레코드 전량**)",
    ]
    for rev, count in sorted(report.standards_by_revision.items()):
        lines.append(f"  - {rev}: 레코드 {count}")
    lines += [
        f"- 소단원(unit) 코퍼스: `{report.units_root}` — 상태 **{report.units_status}** · "
        f"파일 {len(report.units)}개 · 파싱 실패 {len(report.unit_parse_errors)}건",
    ]

    lines += [
        "",
        "## 1. 성취기준 커버리지 (레코드 기준, 분모=전체 개정 통합)",
        "",
        f"- 분모(대장 레코드 전량): **{report.standards_record_count}**",
        f"- 커버된 레코드: **{report.covered_record_count}** "
        f"({_pct(report.covered_record_count, report.standards_record_count)})",
        f"- 커버된 고유 코드: **{len(report.covered_codes)}** / "
        f"고유 코드 전량 {report.standards_unique_code_count}",
        f"- 0커버 고유 코드: **{len(report.zero_coverage_codes)}**",
    ]

    lines += ["", "### 1.1 커버된 성취기준 목록", ""]
    if not report.covered_entries:
        lines.append("- 없음(어떤 unit도 성취기준을 인용하지 않음).")
    else:
        shown = report.covered_entries[:max_covered_display]
        remainder = len(report.covered_entries) - len(shown)
        lines += ["| 코드 | 개정 | 학교급 | 영역 | 소영역 |", "|---|---|---|---|---|"]
        for e in shown:
            lines.append(
                f"| `{e.code}` | {e.revision} | {e.school_type} | {e.domain} | {e.sub_domain} |"
            )
        if remainder > 0:
            lines.append(f"\n…외 **{remainder}**건(전량은 `--json` 산출물의 `covered_entries`).")

    lines += [
        "",
        "### 1.2 개정(curriculum_revision)별 커버율",
        "",
        "| 개정 | 커버 | 분모 | 커버율 |",
        "|---|---:|---:|---:|",
    ]
    for rev, (cov, tot) in _sorted_bucket(report.coverage_by_revision):
        lines.append(f"| {rev} | {cov} | {tot} | {_pct(cov, tot)} |")

    lines += [
        "",
        "### 1.3 학교급별 커버율",
        "",
        "| 학교급 | 커버 | 분모 | 커버율 |",
        "|---|---:|---:|---:|",
    ]
    for school, (cov, tot) in _sorted_bucket(report.coverage_by_school_type):
        lines.append(f"| {school} | {cov} | {tot} | {_pct(cov, tot)} |")

    lines += [
        "",
        "### 1.4 영역(domain)별 커버율",
        "",
        "| 영역 | 커버 | 분모 | 커버율 |",
        "|---|---:|---:|---:|",
    ]
    for domain, (cov, tot) in _sorted_bucket(report.coverage_by_domain):
        lines.append(f"| {domain} | {cov} | {tot} | {_pct(cov, tot)} |")

    lines += ["", "## 2. k_type(CONCEPT/PROCEDURE/REPRESENT/MODELING) 분포", ""]
    if not report.k_type_totals:
        lines.append("- 목표(objective) 0건 — k_type 분포 없음.")
    else:
        lines += ["| k_type | 개수 |", "|---|---:|"]
        for k_type, count in _sorted_counts(report.k_type_totals):
            lines.append(f"| `{k_type}` | {count} |")
    lines.append(f"- 목표(objective) 총계: **{report.objectives_total}**")

    lines += ["", "### 2.1 유닛별 k_type 분포", ""]
    k_type_cols = [k for k, _ in _sorted_counts(report.k_type_totals)]
    if not report.units:
        lines.append("- 소단원(unit) 파일 0건.")
    else:
        lines += [
            "| 유닛 파일 | " + " | ".join(f"`{k}`" for k in k_type_cols) + " | 합계 |",
            "|---" * (len(k_type_cols) + 2) + "|",
        ]
        for name in report.sorted_units():
            row = report.per_unit_k_type.get(name, {})
            cells = " | ".join(str(row.get(k, 0)) for k in k_type_cols)
            lines.append(f"| `{name}` | {cells} | {sum(row.values())} |")

    lines += [
        "",
        "## 3. 유닛(unit) 파일별 분해",
        "",
        "| 파일 | unit_id | curriculum_rev(참고) | standard_codes 수 | objectives 수 |",
        "|---|---|---|---:|---:|",
    ]
    units_by_name = {u.file_name: u for u in report.units}
    for name in report.sorted_units():
        u = units_by_name[name]
        uid = u.unit_id if u.unit_id is not None else UNTAGGED_UNIT_ID
        rev = u.curriculum_rev if u.curriculum_rev is not None else "(없음)"
        lines.append(
            f"| `{name}` | {uid} | {rev} | {len(u.standard_codes)} | {len(u.objectives)} |"
        )

    lines += [
        "",
        "## 4. 정직 회계 (누락·미지 값)",
        "",
        "> 조용히 버리지 않는다 — 아래가 모두 0이어야 위 수치를 액면 그대로 읽을 수 있다.",
        "",
        "| 항목 | 건수 |",
        "|---|---:|",
        f"| 유닛 파일 파싱 실패 | {len(report.unit_parse_errors)} |",
        f"| unit_id 없는 유닛 | {report.units_missing_unit_id} |",
        f"| standard_codes 없는 유닛 | {report.units_without_standard_codes} |",
        f"| standard_code 없는 objective | {report.objectives_without_standard_code} |",
        f"| k_type 없는 objective | {report.objectives_without_k_type} |",
        f"| unit 목록 밖 코드를 인용한 objective | {report.objective_code_outside_unit_list} |",
        f"| 대장에 없는 성취기준 코드(unit 인용, 종) | {len(report.unknown_standard_codes)} |",
    ]
    if report.unknown_standard_codes:
        lines += ["", "### 4.1 대장에 없는 성취기준 코드(unit이 인용)", ""]
        for code, count in _sorted_counts(report.unknown_standard_codes):
            lines.append(f"- `{code}` — {count}회 인용")
    if report.unit_parse_errors:
        lines += ["", "### 4.2 유닛 파일 파싱 실패", ""]
        for err in report.unit_parse_errors:
            lines.append(f"- `{err.unit_file}`: {err.error_type} — {err.detail}")
    lines.append("")
    return "\n".join(lines)


def report_to_json(report: CoverageReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "units_root": str(report.units_root),
        "units_status": report.units_status,
        "units": [
            {
                "file_name": u.file_name,
                "unit_id": u.unit_id,
                "curriculum_rev": u.curriculum_rev,
                "standard_codes": list(u.standard_codes),
                "objective_count": len(u.objectives),
            }
            for u in report.units
        ],
        "unit_parse_errors": [
            {"unit_file": e.unit_file, "error_type": e.error_type, "detail": e.detail}
            for e in report.unit_parse_errors
        ],
        "standards": {
            "record_count": report.standards_record_count,
            "unique_code_count": report.standards_unique_code_count,
            "record_count_by_revision": report.standards_by_revision,
            "covered_record_count": report.covered_record_count,
            "coverage_rate": report.coverage_rate,
            "covered_code_count": len(report.covered_codes),
            "zero_coverage_code_count": len(report.zero_coverage_codes),
        },
        "covered_codes": list(report.covered_codes),
        "zero_coverage_codes": list(report.zero_coverage_codes),
        "covered_entries": [
            {
                "code": e.code,
                "norm_id": e.norm_id,
                "revision": e.revision,
                "school_type": e.school_type,
                "subject": e.subject,
                "domain": e.domain,
                "sub_domain": e.sub_domain,
            }
            for e in report.covered_entries
        ],
        "coverage_by_revision": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_revision.items()
        },
        "coverage_by_school_type": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_school_type.items()
        },
        "coverage_by_domain": {
            k: {"covered": v[0], "total": v[1]} for k, v in report.coverage_by_domain.items()
        },
        "k_type_totals": report.k_type_totals,
        "per_unit_k_type": report.per_unit_k_type,
        "objectives_total": report.objectives_total,
        "honest_accounting": {
            "unit_parse_error_files": len(report.unit_parse_errors),
            "units_missing_unit_id": report.units_missing_unit_id,
            "units_without_standard_codes": report.units_without_standard_codes,
            "objectives_without_standard_code": report.objectives_without_standard_code,
            "objectives_without_k_type": report.objectives_without_k_type,
            "objective_code_outside_unit_list": report.objective_code_outside_unit_list,
            "unknown_standard_codes": report.unknown_standard_codes,
        },
    }


def dump_json(report: CoverageReport) -> str:
    """JSON 직렬화 — 키 정렬·들여쓰기 고정으로 같은 입력에 같은 바이트를 보장(결정론)."""
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — 경로 해석·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 커버리지 관측 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    소단원(unit) 코퍼스가 비어 있거나 디렉터리가 없어도(현재 저장소 상태를 포함) exit 0이다 —
    그 자체가 이 리포트가 관측하려는 정상 상태이지 오류가 아니기 때문이다(모듈 docstring
    `UnitsLoad.status` 참조). exit 2는 *분모 자체를 모르는* 입력 오류(성취기준 대장 부재·파싱
    불가)에만 쓴다. 유닛 파일 단위 파싱 실패는 리포트에 카운트로 실리고 종료 코드에 영향을
    주지 않는다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.objective_coverage",
        description=(
            "학습목표(Objective) 커버리지 관측 리포트(CUR-02) — 성취기준 대비 소단원 커버율· "
            "k_type 분포. 결정론·게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--standards",
        type=Path,
        default=DEFAULT_STANDARDS_PATH,
        help=f"NCIC 성취기준 JSON 경로(기본 {DEFAULT_STANDARDS_PATH}).",
    )
    parser.add_argument(
        "--units-root",
        type=Path,
        default=DEFAULT_UNITS_ROOT,
        help=f"소단원(unit) DSL YAML 디렉터리(기본 {DEFAULT_UNITS_ROOT}).",
    )
    parser.add_argument(
        "--max-covered-display",
        type=int,
        default=100,
        help="본문(§1.1)에 나열할 커버된 성취기준 최대 개수(기본 100·전량은 --json).",
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

    units_load = load_units(args.units_root)
    report = build_report(units_load, catalog)
    print(render_report(report, max_covered_display=args.max_covered_display))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
