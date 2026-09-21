"""증거 4층 경계 정본(EOS-79)의 **표가 실물을 가리키는가** 동결.

이 테스트가 검사하는 것과 검사하지 않는 것을 먼저 못박는다 — 문서 자신이 §3에 같은 말을 적었고,
그 약속을 여기서 기계로 지킨다.

**검사한다**
- 귀속표가 지목한 테이블이 `db/models/`에 `__tablename__`으로 **실재하는가**. 모델을 지우거나
  이름을 바꾸면 표가 허구가 되므로 red.
- 배정 라벨이 허용 6종인가. 새 층을 슬쩍 늘리면 red(§4 "층을 늘리지 않는다"의 기계 짝).
- 실재하는 증거 테이블이 표에서 **빠지지 않았는가**(누락 방향) — 단, 증거 축과 무관한 테이블까지
  강제하면 무차별 red가 되므로 이 방향만 `_EVIDENCE_MODULES`로 한정한다. 실재 검사(위)는 반대로
  `db/models/` **전체**를 본다: 표가 어느 모듈의 테이블을 가리키든 실재해야 하기 때문이다.
  그래서 `timeseries.py`·`user.py`처럼 비증거 테이블이 섞인 모듈의 증거 테이블은 표에 있어도
  되고, 그 모듈의 나머지 테이블은 등재를 강요받지 않는다.

**검사하지 않는다**
- **배정이 옳은가.** `problem_attempt`를 Mastery라고 적어도 이 테스트는 통과한다. 그 판정은
  사람의 것이며(문서 §3), 정적으로 재려면 컬럼명 화이트리스트가 필요한데 그것은 표기 변형에서
  뚫리는 "금지 패턴 열거"가 된다(CLAUDE.md 2026-09-01 ①).

**파서가 위장하지 않는다** — 마커 부재·빈 목록·형식 붕괴는 "위반 0 통과"가 아니라 **예외로
실패**한다(`test_required_checks_doc.py` 선례). 파서를 무력화하면 이 파일 전체가 위장이 되므로,
그 실패 자체를 테스트로 못박는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATH = _REPO_ROOT / "docs" / "architecture" / "evidence_layer_boundary.md"
_MODELS_DIR = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "db" / "models"

_BEGIN = "<!-- EVIDENCE_LAYER_MAP_BEGIN"
_END = "<!-- EVIDENCE_LAYER_MAP_END -->"

# 허용 배정 6종 — §1의 4층 + 복수 배정(혼재) + 축 밖(반례). 늘리려면 문서 §4의 근거가 먼저다.
_ALLOWED_LAYERS = frozenset({"Attempt", "Evaluation", "Assessment", "Mastery", "혼재", "반례"})

# **누락 검사 전용** 모듈 — 여기 있는 모듈의 테이블은 전부 표에 있어야 한다. 증거 테이블만 담긴
# 모듈로 한정한다(`user.py`·`timeseries.py`·`dialogue.py`처럼 비증거 테이블이 섞인 모듈을 넣으면
# 사용자·결제 테이블까지 등재를 강요해 무차별 red가 된다). 실재 검사는 이 목록을 쓰지 않는다.
_EVIDENCE_MODULES = (
    "activity.py",
    "answer_submission.py",
    "student_solution_step.py",
    "hint_usage.py",
    "evidence_link.py",
    "evidence_event.py",
    "assessment.py",
    "misconception_hypothesis.py",
    "verified_solution.py",
    "dead_end_log.py",
    "atom_probe.py",
    "review_timer_event.py",
)

# 표 행: | `테이블` | 좌표 | **배정**(괄호 설명 선택) | writer | 근거 |
_ROW = re.compile(
    r"^\|\s*`(?P<table>[a-z_]+)`\s*\|[^|]*\|\s*\*\*(?P<layer>[^*]+)\*\*[^|]*\|",
    re.MULTILINE,
)
_TABLENAME = re.compile(r'^\s*__tablename__\s*=\s*"(?P<name>[a-z_]+)"', re.MULTILINE)


def _marker_block(text: str) -> str:
    """마커 블록 본문. 마커가 없으면 **예외** — 조용히 빈 문자열을 돌려주지 않는다."""
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1 or end <= start:
        raise AssertionError(
            f"{_DOC_PATH.name}: EVIDENCE_LAYER_MAP 마커 블록을 찾지 못했다 "
            f"(begin={start}, end={end}). 표를 옮겼다면 마커도 함께 옮겨라."
        )
    return text[start:end]


def parse_map(text: str) -> dict[str, str]:
    """마커 블록 → {테이블명: 배정}. 행이 하나도 없으면 예외(빈 통과 금지)."""
    rows = {m.group("table"): m.group("layer").strip() for m in _ROW.finditer(_marker_block(text))}
    if not rows:
        raise AssertionError(
            f"{_DOC_PATH.name}: 마커 블록 안에 귀속 행이 하나도 없다 — 표 형식이 깨졌거나 비었다."
        )
    return rows


def _scan_tablenames(modules: tuple[str, ...] | None) -> dict[str, str]:
    """{테이블명: 파일명}. `modules=None`이면 `db/models/` 전체를 훑는다.

    대상 모듈이 사라졌거나 한 건도 못 찾으면 **예외** — 스캔이 헛돌면 "위반 0 통과"처럼 보이는데
    그건 통과가 아니라 측정 실패다.
    """
    paths: list[Path]
    if modules is None:
        paths = sorted(p for p in _MODELS_DIR.glob("*.py") if p.name != "__init__.py")
    else:
        missing = [m for m in modules if not (_MODELS_DIR / m).is_file()]
        if missing:
            raise AssertionError(
                f"증거 축 모듈이 사라졌다: {missing} — 이동·개명했다면 _EVIDENCE_MODULES를 고쳐라. "
                "대상을 못 찾은 스캔은 '위반 0'이 아니라 측정 실패다."
            )
        paths = [_MODELS_DIR / m for m in modules]

    found: dict[str, str] = {}
    for path in paths:
        for match in _TABLENAME.finditer(path.read_text(encoding="utf-8")):
            found[match.group("name")] = path.name
    if not found:
        raise AssertionError(
            f"__tablename__을 한 건도 찾지 못했다(파일 {len(paths)}건) — 파서 또는 경로가 깨졌다."
        )
    return found


# ──────────────────────────────────────────────────────────────────────
# ① 문서 실재와 집행 범위 명시
# ──────────────────────────────────────────────────────────────────────
def test_doc_exists() -> None:
    assert _DOC_PATH.is_file(), f"정본 문서 부재: {_DOC_PATH}"


def test_doc_states_it_does_not_enforce_assignment() -> None:
    """ "정본화 ≠ 집행" 경고가 **제목으로** 있는가 — 본문 어딘가의 문자열이 아니라 구조로 본다.

    substring 검사면 표의 근거 칸에 같은 말이 우연히 들어가도 통과한다(위장). 제목 정규식이라
    경고 절을 통째로 지우면 red다.
    """
    text = _DOC_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"^>\s*##\s*⚠️?\s*정본화 ≠ 집행", text, re.MULTILINE
    ), "정본화 ≠ 집행 경고 제목이 없다 — 이 문서가 배정을 강제한다는 오해를 막는 절이다."


# ──────────────────────────────────────────────────────────────────────
# ② 표 ↔ 실물 대조
# ──────────────────────────────────────────────────────────────────────
def test_every_mapped_table_exists_in_models() -> None:
    """표가 지목한 테이블이 전부 실재하는가 — 지우거나 개명하면 red. 대상은 db/models 전체."""
    declared = _scan_tablenames(None)
    mapped = parse_map(_DOC_PATH.read_text(encoding="utf-8"))
    ghosts = sorted(t for t in mapped if t not in declared)
    assert not ghosts, (
        f"귀속표가 실재하지 않는 테이블을 가리킨다: {ghosts}. "
        f"모델을 옮겼다면 {_DOC_PATH.name}의 좌표도 함께 고쳐라(허구가 된 표는 판정 근거가 아니다)."
    )


def test_every_evidence_table_is_mapped() -> None:
    """증거 축 모듈의 테이블이 표에서 빠지지 않았는가 — 새 증거 모델을 등재 없이 추가하면 red."""
    declared = _scan_tablenames(_EVIDENCE_MODULES)
    mapped = parse_map(_DOC_PATH.read_text(encoding="utf-8"))
    unmapped = sorted(t for t in declared if t not in mapped)
    assert not unmapped, (
        f"증거 축 테이블이 귀속표에 없다: {unmapped}. "
        f"{_DOC_PATH.name} §2에 배정을 적어라 — 배정 불가면 '혼재'·축 밖이면 '반례'로 적는다."
    )


def test_layer_labels_are_from_the_allowed_set() -> None:
    """층을 슬쩍 늘리지 못하게 — §4 "층을 늘리지 않는다"의 기계 짝."""
    mapped = parse_map(_DOC_PATH.read_text(encoding="utf-8"))
    unknown = sorted({v for v in mapped.values() if v not in _ALLOWED_LAYERS})
    assert not unknown, (
        f"허용되지 않은 배정 라벨: {unknown} (허용: {sorted(_ALLOWED_LAYERS)}). "
        "층을 늘리려면 문서 §4에 근거를 먼저 적고 이 목록을 함께 고쳐라."
    )


def test_all_four_layers_are_actually_used() -> None:
    """4층이 표에서 실제로 쓰이는가 — 정의만 있고 아무것도 배정 안 된 층이 있으면 정의가 공허하다.

    `Evaluation`은 단독 좌석이 없어 `혼재`로만 나타나므로(문서 §2), 혼재 설명 칸까지 포함해 본다.
    """
    block = _marker_block(_DOC_PATH.read_text(encoding="utf-8"))
    for layer in ("Attempt", "Evaluation", "Assessment", "Mastery"):
        assert layer in block, f"{layer} 층이 귀속표 어디에도 배정되지 않았다 — 정의가 공허하다."


# ──────────────────────────────────────────────────────────────────────
# ③ 파서 자체가 위장하지 않는가 (결함 주입)
# ──────────────────────────────────────────────────────────────────────
def test_missing_marker_raises_rather_than_passing_empty() -> None:
    with pytest.raises(AssertionError, match="마커 블록을 찾지 못했다"):
        parse_map("# 문서\n\n| `problem_attempt` | x | **Attempt** | y | z |\n")


def test_empty_block_raises_rather_than_passing_empty() -> None:
    with pytest.raises(AssertionError, match="귀속 행이 하나도 없다"):
        parse_map(f"{_BEGIN} -->\n\n(표 없음)\n\n{_END}\n")


def test_parser_reads_rows_only_from_inside_the_marker_block() -> None:
    """블록 **밖**의 표 행을 주워 오면, 마커를 지워도 통과하는 위장이 된다."""
    text = (
        "| `outside_table` | x | **Attempt** | y | z |\n"
        f"{_BEGIN} -->\n"
        "| `problem_attempt` | x | **혼재** (Attempt + Evaluation) | y | z |\n"
        f"{_END}\n"
    )
    assert parse_map(text) == {"problem_attempt": "혼재"}


def test_missing_evidence_module_is_a_measurement_failure() -> None:
    """대상 모듈을 못 찾은 스캔은 '위반 0'이 아니라 실패다."""
    with pytest.raises(AssertionError, match="증거 축 모듈이 사라졌다"):
        _scan_tablenames(("does_not_exist.py",))
