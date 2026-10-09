"""공식(formula) 지식 자산 도달률 관측 리포트 CLI — 빌드타임 결정론(정적 스캔·DB 0·LLM 0·HTTP 0).
KG-03 acceptance①.

설계 정본: `docs/architecture/knowledge_module_gap_review_r3.md` §2 G1. S4-06(D3)이
`FormulaNode` 25건·`constraints` 15건·`mnemonic` 14건을 *저작*했지만, 도달 렌즈로 보면
write-only다 — api/ 내 formula 참조 0건·자기 모듈 밖 심볼 참조 0건(주석 제외)·Flutter 소비
0건. 이 리포트는 그 "저작됐으나 소비되지 않음"을 정적 스캔으로 가시화한다. KG-01
(`concept_reach_report.py`)의 dataclass 기반 로더/집계/렌더/JSON/CLI 구조를 그대로 복제한다.

**게이트가 아니다**(VIZ-01·KG-01과 동일 원칙) — 도달 0건이어도 exit 1을 내지 않는다. 목적은
도달률을 올리는 것이 아니라 *관측 가능하게* 만드는 것이다(활성화가 아니라 가시화 —
acceptance⑥). 공식 API 신설·공식 학생 노출·`formula_refs` 충전(Phase 5b 승계)은 범위 밖.

**집행 지점(acceptance② — '미도달' 판정이 읽히는 곳)**:
  - 정본 판정 소비처 = `tests/backend/harness/test_formula_reach_report.py`(실 코퍼스 스모크
    anchor 포함). CI 배선 실측 인용: `.github/workflows/ci.yml` backend 잡이
    `working-directory: src/backend`에서 "Pytest (with coverage)" 스텝(bare `pytest
    --cov=whymath_backend ...`)을 실행하고, `src/backend/pyproject.toml`의
    `testpaths = ["../../tests/backend"]`가 `tests/backend/harness/`를 수집한다 — 즉 이
    테스트 파일은 저장소에 존재만 하는 것이 아니라 backend 잡에서 실제로 돈다(OPS-03·OPS-10).
  - 전용 CI 잡·상시 JSON 산출 배선은 **없다** — `concept-reach-guard`(OPS-23)와 달리 이
    리포트는 mobile-only PR 회귀 가드가 아니라 관측 리포트다(태스크 명시: 전용 잡 신설 금지).
    JSON은 `--json <경로>` 지정 시에만 그 경로에 쓴다(고정 산출 경로 없음).

관측 표면 4종(태스크 a~d):
  (a) `api_formula_seat` — formula_node 읽기 API *좌석 존재 여부*.
      `api/**/*.py`에서 대소문자 무시 `formula` 참조를 스캔한다(현행 0 = 읽기 API 미신설).
  (b) `formula_symbol_refs` — `formula_id`·`FormulaNode`의 자기 모듈 밖 참조 수.
      자기 모듈 = `l1/formula_graph/**`·`db/models/formula_node.py`. 주석·docstring 라인 제외.
  (c) 코퍼스 충전율 — `data/corpus/formula_graph_v1/formulas.jsonl`의
      `constraints`·`mnemonic`·`canonical_signature` 충전/총계. **도달 축이 아니라 저작 축**
      이므로 표면 status(도달/미도달)가 아니라 별개 필드(`corpus_fill`)로 낸다(acceptance③ —
      "저작됐다 15/25"와 "도달했다 0"의 분리, KG-01의 reviewed_only 공집합 vs reach=0 선례).
  (d) `mobile_formula_refs` — Flutter 클라 소비 참조 수. `src/mobile/lib/**/*.dart`에서
      formula를 포함하는 `/v1/` 경로 리터럴 + `formula_id` 심볼을 스캔한다(현행 0).
      bare 토큰 스캔은 OCR '수식(formula)' 도메인 용어 오탐 6건(2026-08-11 실측)을 내므로
      쓰지 않는다 — 표면 note에 상세.

**anchor 성질(acceptance⑤)**: 총 공식 수·필드 충전 수는 하드코딩이 아니라 매 실행 코퍼스
파일을 읽어 재실측한다 — 분모가 자라는데 문서가 안 따라가는 stale을 리포트 자체가 잡는다
(`knowledge_module_gap_review_r3.md` §4 교훈). 실코퍼스 스모크 테스트가 현행 기대값
(공식 25·constraints 15·mnemonic 14·canonical_signature 0·전 표면 미도달)을 assert해 회귀
anchor로 동결한다 — 값이 바뀌면 테스트가 알려준다.

**알려진 한계(1급으로 노출·숨기지 않음 — KG-01 `method_ambiguous_groups` 관례)**:
  1. 주석·docstring 제외는 *라인 단위 휴리스틱*이다 — 파이썬은 `#` 시작 라인과 삼중따옴표
     블록 라인, dart는 `//` 시작 라인을 제외한다. 코드 라인의 꼬리 주석·dart 블록 주석
     (`/* */`)은 구분하지 않는다(그 안의 참조는 과대 계수될 수 있다 — 현행 코퍼스에는 없음).
  2. 표면 (b)는 자기 모듈 외에 3개 경로를 추가 제외하며 그 목록·사유를
     `SYMBOL_SCAN_EXCLUSIONS`로 렌더·JSON에 그대로 노출한다:
     - `db/models/__init__.py` — 모델 배럴의 재수출(import 1줄·`__all__` 등재 1줄·주석 1줄,
       2026-08-11 실측). 재수출은 프로젝션 좌석의 *등록*이지 *소비*가 아니다 — 이를 도달로
       세면 write-only 상태가 '도달'로 위장된다(정직 표기 위반).
     - `harness/formula_reach_report.py` — 관측기 자신. 스캔 패턴 문자열·라벨이 자기 자신에
       매치돼 영구 '도달' 위장이 된다(변별력 상실 방지).
     - `l3/curriculum_notation_gate.py` — 교육과정 표기 범위 게이트(MATH-06). 수식 그래프
       코퍼스를 표기 회계로 읽을 뿐 formula 노드를 소비하지 않는다(생성물 회계 전용).
  3. 표면 (b)의 스캔 루트는 `whymath_backend` 패키지다 — `src/backend/alembic/`의 마이그레이션
     (`20260708_1200_b3c4d5e6f0a1_formula_node_projection.py`)은 루트 밖이라 계수되지 않는다.
     이는 의도된 경계다: DDL은 좌석 *생성*이지 *소비*가 아니다.

사용:
    python -m whymath_backend.harness.formula_reach_report
    python -m whymath_backend.harness.formula_reach_report --json out/formula_reach.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "FILL_FIELDS",
    "SURFACES",
    "SYMBOL_SCAN_EXCLUSIONS",
    "FieldFill",
    "FormulaCorpusFill",
    "FormulaReachReport",
    "SurfaceReach",
    "SurfaceSpec",
    "build_report",
    "dump_json",
    "load_corpus",
    "load_scan_root",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_INPUT_ERROR = 2

# harness→whymath_backend→backend→src→repo 루트(concept_reach_report.py와 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BACKEND_PKG_ROOT = _REPO_ROOT / "src" / "backend" / "whymath_backend"
DEFAULT_BACKEND_API_ROOT = DEFAULT_BACKEND_PKG_ROOT / "api"
DEFAULT_MOBILE_LIB_ROOT = _REPO_ROOT / "src" / "mobile" / "lib"
DEFAULT_CORPUS_PATH = _REPO_ROOT / "data" / "corpus" / "formula_graph_v1" / "formulas.jsonl"

# 이 이름의 디렉터리 아래는 스캔에서 제외한다(KG-01 "20 vs 13" 재발 방지 방어 가드 답습) —
# 기본 루트들은 이미 test 밖이지만, override된 루트가 테스트 목 리터럴을 섞지 않도록 이중 방어.
_EXCLUDED_DIR_NAMES = {"test", "tests"}

# 표면 (b) 전용 경로 제외 목록: (스캔 루트 상대 posix 경로, 제외 사유).
# 렌더·JSON에 그대로 노출한다 — 제외를 숨기면 '0'의 의미를 검증할 수 없다(정직 표기).
SYMBOL_SCAN_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("l1/formula_graph", "자기 모듈 — 공식 그래프 정의·적재기 자신(태스크 정의)"),
    ("db/models/formula_node.py", "자기 모듈 — PG 프로젝션 모델 정의 자신(태스크 정의)"),
    (
        "db/models/__init__.py",
        "모델 배럴 재수출(import·__all__ 등재) — 좌석 등록이지 소비가 아니다"
        "(2026-08-11 실측: import 1줄·__all__ 1줄·주석 1줄뿐, 사용 코드 0)",
    ),
    (
        "harness/formula_reach_report.py",
        "관측기 자신 — 스캔 패턴 문자열이 자기 자신에 매치돼 영구 '도달' 위장이 된다",
    ),
    (
        "l3/curriculum_notation_gate.py",
        "교육과정 표기 범위 게이트(MATH-06) — 수식 그래프 코퍼스를 *표기 회계*로 읽는다"
        "(레코드의 슬러그 문자열 `formula_id`). 학습 경로·API가 formula 노드를 쓰는 소비가 아니라 "
        "생성물 회계라, 이를 도달로 세면 미소비 상태가 '도달'로 위장된다",
    ),
)

# 표면 (c) 충전율을 재는 코퍼스 필드 3종(acceptance c — 순서 고정·결정론).
FILL_FIELDS: tuple[str, ...] = ("constraints", "mnemonic", "canonical_signature")


@dataclass(slots=True, frozen=True)
class SurfaceSpec:
    """표면 1건의 정의(코드 상수 — 로드 대상 아님. 표면 목록 자체가 바뀌면 코드를 고친다)."""

    key: str
    label: str
    definition_location: str
    scan_root_kind: str  # "backend_api" | "backend_pkg" | "mobile_lib"
    glob: str
    pattern: re.Pattern[str]
    pattern_id: str
    lang: str  # "python" | "dart" — 주석·docstring 라인 제외 규칙 선택
    exclusions: tuple[tuple[str, str], ...] = ()
    note: str | None = None


SURFACES: tuple[SurfaceSpec, ...] = (
    SurfaceSpec(
        key="api_formula_seat",
        label="formula_node 읽기 API 좌석(api/ 내 formula 참조)",
        definition_location="db/models/formula_node.py (프로젝션) — 스캔 대상은 api/**/*.py",
        scan_root_kind="backend_api",
        glob="*.py",
        pattern=re.compile(r"formula", re.IGNORECASE),
        pattern_id="token:formula@api",
        lang="python",
        note=(
            "'학생이 호출하는가'가 아니라 'api/ 어디든 formula를 읽는 좌석 자체가 있는가'를 "
            "본다(KG-01 flashcards 축과 동형). 현행 0 = 읽기 API 미신설(write-only)."
        ),
    ),
    SurfaceSpec(
        key="formula_symbol_refs",
        label="formula_id·FormulaNode 자기 모듈 밖 심볼 참조",
        definition_location="l1/formula_graph/**·db/models/formula_node.py 밖의 backend 전역",
        scan_root_kind="backend_pkg",
        glob="*.py",
        pattern=re.compile(r"\b(?:formula_id|FormulaNode)\b"),
        pattern_id="symbol:formula_id|FormulaNode",
        lang="python",
        exclusions=SYMBOL_SCAN_EXCLUSIONS,
        note=(
            "주석·docstring 라인 제외(라인 휴리스틱 — 모듈 docstring '알려진 한계' 참조). "
            "제외 경로·사유는 symbol_scan_exclusions 필드에 전량 노출."
        ),
    ),
    SurfaceSpec(
        key="mobile_formula_refs",
        label="Flutter 클라 소비 참조(src/mobile/lib 내 formula 관련 /v1/ 리터럴·formula_id)",
        definition_location="src/mobile/lib/**/*.dart — formula 관련 /v1/ 리터럴 + formula_id",
        scan_root_kind="mobile_lib",
        glob="*.dart",
        pattern=re.compile(r"/v1/[^'\"\s]*formula|\bformula_id\b", re.IGNORECASE),
        pattern_id="path-or-symbol:/v1/*formula|formula_id@mobile",
        lang="dart",
        note=(
            "공식 API 자체가 0이라 특정 /v1/ 경로 템플릿을 나열할 수 없다 — formula를 포함하는 "
            "/v1/ 경로 리터럴 + formula_id 심볼(대소문자 무시)만 잡는다(// 주석 라인 제외). "
            "bare 토큰 'formula' 스캔은 쓰지 않는다: 2026-08-11 실측에서 OCR '수식(formula)' "
            "도메인 용어(isFormula·ocrContentTypeFormula)·결함 신고 enum(formulaError) 오탐 "
            "6건이 이 표면을 거짓 '도달'로 위장했다 — 공식 그래프 자산 소비가 아니다."
        ),
    ),
)

_TRIPLE_QUOTES = ('"""', "'''")


def load_scan_root(path: Path, *, label: str) -> Path:
    """스캔 루트 디렉터리 존재 검증(KG-01 동형) — "입력을 못 읽음"과 "읽었는데 0건(미도달)"은
    다른 실패 축이므로 여기서 분리한다.

    Raises:
        ValueError: 디렉터리가 아니거나 존재하지 않음.
    """
    if not path.is_dir():
        raise ValueError(f"{label} 스캔 루트가 디렉터리가 아니거나 존재하지 않음: {path}")
    return path


def load_corpus(path: Path) -> tuple[dict[str, Any], ...]:
    """공식 코퍼스(jsonl) 로드 — 행 단위 JSON 오브젝트 검증(정직 실패·조용한 skip 없음).

    Raises:
        ValueError: 파일 부재·JSON 파싱 실패·행이 오브젝트가 아님.
    """
    if not path.is_file():
        raise ValueError(f"공식 코퍼스 파일이 존재하지 않음: {path}")
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"코퍼스 {path.name}:{lineno} JSON 파싱 실패: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(
                f"코퍼스 {path.name}:{lineno} 행이 오브젝트가 아님: {type(row).__name__}"
            )
        rows.append(row)
    return tuple(rows)


def _is_excluded_dir(path: Path, root: Path) -> bool:
    return any(part.lower() in _EXCLUDED_DIR_NAMES for part in path.relative_to(root).parts)


def _python_significant_lines(text: str) -> Iterator[tuple[int, str]]:
    """파이썬 소스에서 주석(`#` 시작)·docstring(삼중따옴표 블록) *라인*을 제외하고 순회.

    라인 단위 휴리스틱이다(모듈 docstring '알려진 한계' ①) — 삼중따옴표가 등장하는 라인은
    여는 쪽·닫는 쪽·한 줄짜리 모두 제외하고, 홀수 개 등장 시 블록 내부로 전환한다.
    """
    in_block: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if in_block is not None:
            if in_block in line:
                in_block = None
            continue  # 블록 내부·닫는 라인 모두 제외
        if line.lstrip().startswith("#"):
            continue
        delim = next((d for d in _TRIPLE_QUOTES if d in line), None)
        if delim is not None:
            if line.count(delim) % 2 == 1:
                in_block = delim
            continue  # 삼중따옴표 등장 라인은 열든 닫든 한 줄이든 제외
        yield lineno, line


def _dart_significant_lines(text: str) -> Iterator[tuple[int, str]]:
    """dart 소스에서 `//` 시작 주석 라인을 제외하고 순회(블록 주석 `/* */`은 미구분 — 한계 ①)."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("//"):
            continue
        yield lineno, line


def _significant_lines(text: str, lang: str) -> Iterator[tuple[int, str]]:
    if lang == "python":
        return _python_significant_lines(text)
    return _dart_significant_lines(text)


def _is_excluded_path(rel_posix: str, exclusions: tuple[tuple[str, str], ...]) -> bool:
    """상대 posix 경로가 제외 목록(파일 정확 일치 또는 디렉터리 prefix)에 해당하는가."""
    for excluded, _reason in exclusions:
        if rel_posix == excluded or rel_posix.startswith(excluded.rstrip("/") + "/"):
            return True
    return False


def _scan_sites(
    root: Path,
    glob: str,
    pattern: re.Pattern[str],
    lang: str,
    exclusions: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """`root` 아래 `glob` 파일의 유의미 라인(주석·docstring 제외)에서 `pattern` 매치를 모은다.

    반환은 "root-상대경로:라인번호" — 참조 *수*(라인 매치 발생 수)가 reach_count가 된다.
    결정론(정렬 순회)·부작용 0. 디코드 실패 파일은 조용히 skip(바이너리·비UTF-8 혼입 방어 —
    KG-01 `_scan` 동형).
    """
    sites: list[str] = []
    for path in sorted(root.rglob(glob)):
        if _is_excluded_dir(path, root):
            continue
        rel_posix = path.relative_to(root).as_posix()
        if _is_excluded_path(rel_posix, exclusions):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in _significant_lines(text, lang):
            for _match in pattern.finditer(line):
                sites.append(f"{rel_posix}:{lineno}")
    return tuple(sites)


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 도달 리포트(순수 코어)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class SurfaceReach:
    """표면 1건의 도달 관측 결과. 상태는 분수가 아니라 이진 문자열이다(정직 표기 —
    acceptance③: '0건 통과'가 아니라 '미도달')."""

    key: str
    label: str
    definition_location: str
    reach_count: int
    matched_sites: tuple[str, ...]
    status: str  # "도달" | "미도달"
    pattern_id: str
    note: str | None


@dataclass(slots=True, frozen=True)
class FieldFill:
    """코퍼스 필드 1종의 충전 관측(저작 축 — 도달 축이 아니므로 status 없음).

    `keys_present`는 '키가 있는데 null/빈 값'과 '키 자체가 없음'을 구분한다 —
    현행 canonical_signature는 키 자체가 0건(스키마에 아직 없음)이다.
    """

    field: str
    filled: int
    total: int
    keys_present: int


@dataclass(slots=True, frozen=True)
class FormulaCorpusFill:
    """저작(충전) 축 전량 — acceptance③에 따라 도달 표면과 별개 필드로 분리한다."""

    corpus_path: str
    total_formulas: int
    fields: tuple[FieldFill, ...]


@dataclass(slots=True, frozen=True)
class FormulaReachReport:
    """도달 관측 결과 전량(불변·렌더/직렬화의 단일 입력).

    `surfaces`(도달=소비 축)와 `corpus_fill`(저작=충전 축)은 서로 다른 축이다 —
    "constraints 15/25 저작됐다"가 "도달했다"를 함의하지 않는다(acceptance③).
    """

    surfaces: tuple[SurfaceReach, ...]
    corpus_fill: FormulaCorpusFill
    symbol_scan_exclusions: tuple[tuple[str, str], ...]

    @property
    def unreached_count(self) -> int:
        return sum(1 for s in self.surfaces if s.status == "미도달")


def _is_filled(value: Any) -> bool:
    """충전 판정 — None·빈 컨테이너·빈 문자열은 미충전.

    현행 코퍼스의 미충전 형태는 `constraints=[]`(빈 배열)·`mnemonic=null` 두 가지다.
    """
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


def _measure_corpus_fill(corpus_path: Path) -> FormulaCorpusFill:
    """코퍼스 파일을 읽어 총 공식 수·필드 충전 수를 매 실행 재실측(acceptance⑤ — 하드코딩 금지)."""
    rows = load_corpus(corpus_path)
    fields = tuple(
        FieldFill(
            field=field,
            filled=sum(1 for r in rows if _is_filled(r.get(field))),
            total=len(rows),
            keys_present=sum(1 for r in rows if field in r),
        )
        for field in FILL_FIELDS
    )
    return FormulaCorpusFill(corpus_path=str(corpus_path), total_formulas=len(rows), fields=fields)


def build_report(
    *,
    backend_pkg_root: Path = DEFAULT_BACKEND_PKG_ROOT,
    backend_api_root: Path = DEFAULT_BACKEND_API_ROOT,
    mobile_root: Path = DEFAULT_MOBILE_LIB_ROOT,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
) -> FormulaReachReport:
    """도달 표면 3종 + 저작 충전율 → `FormulaReachReport`(순수·부작용 0)."""
    backend_pkg_root = load_scan_root(backend_pkg_root, label="backend 패키지")
    backend_api_root = load_scan_root(backend_api_root, label="backend api")
    mobile_root = load_scan_root(mobile_root, label="mobile lib")

    roots = {
        "backend_api": backend_api_root,
        "backend_pkg": backend_pkg_root,
        "mobile_lib": mobile_root,
    }
    surfaces: list[SurfaceReach] = []
    for spec in SURFACES:
        matched = _scan_sites(
            roots[spec.scan_root_kind], spec.glob, spec.pattern, spec.lang, spec.exclusions
        )
        surfaces.append(
            SurfaceReach(
                key=spec.key,
                label=spec.label,
                definition_location=spec.definition_location,
                reach_count=len(matched),
                matched_sites=matched,
                status="도달" if matched else "미도달",
                pattern_id=spec.pattern_id,
                note=spec.note,
            )
        )

    return FormulaReachReport(
        surfaces=tuple(surfaces),
        corpus_fill=_measure_corpus_fill(corpus_path),
        symbol_scan_exclusions=SYMBOL_SCAN_EXCLUSIONS,
    )


# ──────────────────────────────────────────────────────────────────────────
# 렌더 — 사람이 읽는 마크다운 + 기계가 읽는 JSON
# ──────────────────────────────────────────────────────────────────────────
def render_report(report: FormulaReachReport, *, max_listed: int = 40) -> str:
    """도달 관측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음).

    목록류는 `max_listed`개까지만 본문에 싣고 잘림 사실을 문장으로 남긴다
    (KG-01 `render_report` 관례 답습 — 조용한 절단 금지).
    """
    lines: list[str] = [
        "# 공식 지식 자산 도달 관측 리포트 (KG-03)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(도달 0건이어도 실패시키지 않는다).",
        "> 활성화가 아니라 가시화가 목적이다(acceptance⑥) — 공식 API 신설·학생 노출·",
        "> formula_refs 충전은 범위 밖.",
        "",
        "## 0. 도달(소비) 표면 3종",
        "",
        "| 키 | 표면 | 정의 위치 | 상태 | reach_count |",
        "|---|---|---|---|---:|",
    ]
    for s in report.surfaces:
        lines.append(
            f"| `{s.key}` | {s.label} | `{s.definition_location}` | {s.status} | {s.reach_count} |"
        )
    lines.append(f"\n- 미도달 표면: **{report.unreached_count}/{len(report.surfaces)}**")

    fill = report.corpus_fill
    lines += [
        "",
        "## 1. 저작(충전) 축 — 도달과 별개(acceptance③)",
        "",
        "저작됐다(충전율)와 도달했다(소비 참조)는 서로 다른 축이다 — 아래 충전율이 높아도",
        "위 표면이 미도달이면 자산은 write-only다.",
        "",
        f"- 코퍼스: `{fill.corpus_path}`",
        f"- 총 공식 수(매 실행 재실측 — 하드코딩 아님): **{fill.total_formulas}**",
        "",
        "| 필드 | 충전 | 총계 | 키 존재 행 수 |",
        "|---|---:|---:|---:|",
    ]
    for f in fill.fields:
        lines.append(f"| `{f.field}` | {f.filled} | {f.total} | {f.keys_present} |")

    lines += ["", "## 2. 심볼 스캔 제외 목록(숨기지 않는다)", ""]
    for excluded, reason in report.symbol_scan_exclusions:
        lines.append(f"- `{excluded}` — {reason}")

    all_sites = [site for s in report.surfaces for site in s.matched_sites]
    lines += ["", "## 3. 매치 상세(참조 사이트)", ""]
    if all_sites:
        shown = all_sites[:max_listed]
        lines.append("```")
        lines.extend(shown)
        lines.append("```")
        remainder = len(all_sites) - len(shown)
        if remainder > 0:
            lines.append(f"…외 **{remainder}**건(전량은 `--json` 산출물).")
    else:
        lines.append("(매치 0건 — 전 표면 미도달)")

    notes = [(s.key, s.note) for s in report.surfaces if s.note]
    if notes:
        lines += ["", "## 4. 표면별 특기사항", ""]
        for key, note in notes:
            lines.append(f"- `{key}`: {note}")

    lines.append("")
    return "\n".join(lines)


def report_to_json(report: FormulaReachReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`로 고정)."""
    return {
        "surfaces": [
            {
                "key": s.key,
                "label": s.label,
                "definition_location": s.definition_location,
                "reach_count": s.reach_count,
                "matched_sites": list(s.matched_sites),
                "status": s.status,
                "pattern_id": s.pattern_id,
                "note": s.note,
            }
            for s in report.surfaces
        ],
        "unreached_count": report.unreached_count,
        "corpus_fill": {
            "corpus_path": report.corpus_fill.corpus_path,
            "total_formulas": report.corpus_fill.total_formulas,
            "fields": [
                {
                    "field": f.field,
                    "filled": f.filled,
                    "total": f.total,
                    "keys_present": f.keys_present,
                }
                for f in report.corpus_fill.fields
            ],
        },
        "symbol_scan_exclusions": [
            {"path": excluded, "reason": reason}
            for excluded, reason in report.symbol_scan_exclusions
        ],
    }


def dump_json(report: FormulaReachReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — 경로 해석·입출력만, 집계는 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 도달 관측 리포트를 stdout에 출력. **0=성공 / 2=입력 오류**(1 없음).

    도달 0건이어도 exit 0이다(게이트 아님 — acceptance⑥). exit 2는 스캔 루트·코퍼스 자체를
    읽을 수 없는 입력 오류에만 쓴다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.formula_reach_report",
        description=(
            "공식 지식 자산 도달 관측 리포트(KG-03) — api 좌석·심볼 참조·클라 소비의 도달 여부 "
            "+ 코퍼스 충전율(저작 축). 결정론·게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--backend-pkg-root",
        type=Path,
        default=DEFAULT_BACKEND_PKG_ROOT,
        help="backend 패키지 루트(기본: src/backend/whymath_backend)",
    )
    parser.add_argument(
        "--backend-api-root",
        type=Path,
        default=DEFAULT_BACKEND_API_ROOT,
        help="backend api 루트(기본: src/backend/whymath_backend/api)",
    )
    parser.add_argument(
        "--mobile-root",
        type=Path,
        default=DEFAULT_MOBILE_LIB_ROOT,
        help="Flutter mobile lib 루트(기본: src/mobile/lib)",
    )
    parser.add_argument(
        "--corpus",
        dest="corpus_path",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help="공식 코퍼스 jsonl(기본: data/corpus/formula_graph_v1/formulas.jsonl)",
    )
    parser.add_argument(
        "--max-listed", type=int, default=40, help="본문에 나열할 목록 최대 개수(기본 40)"
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(
            backend_pkg_root=args.backend_pkg_root,
            backend_api_root=args.backend_api_root,
            mobile_root=args.mobile_root,
            corpus_path=args.corpus_path,
        )
    except ValueError as exc:
        print(f"입력 오류 — 입력 검증 실패({type(exc).__name__}): {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    print(render_report(report, max_listed=args.max_listed))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
