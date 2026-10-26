"""코퍼스 사실 단일 원천 (OPS-154).

건수·지문을 원본 파일에서 계산하고, 문서는 그 값을 표식으로 인용한다.

## 왜 있는가

코퍼스 건수(원자 백본 노드·엣지, 오개념 수, 문제은행 건수 …)가 CLAUDE.md·아키텍처 문서·데이터 카드·
런북·코퍼스 자기 선언(`_provenance.json`)에 **손으로** 적혀 있었다. 정본이 바뀔 때마다 사람이 찾아서
고쳤고, 못 찾은 곳은 옛 값으로 남았다(예: 오개념 843건인데 `_provenance.json`은 841건).

## 규칙 세 가지

1. **값은 여기서만 계산한다** — `build_facts()`의 각 항목이 "사실 이름 → 원본에서 세는
   함수"다. 숫자를 손으로 적어 두는 곳은 없다.
2. **문서는 표식으로 인용한다** — 마크다운에 아래처럼 쓴다. 렌더링에서는 주석이 안 보이고
   숫자만 보인다.

       <!-- fact:atom_graph.edges -->2,278<!-- /fact -->

   천 단위 쉼표 없이 쓰려면 `<!-- fact:atom_graph.edges raw -->2278<!-- /fact -->`.
3. **원본이 바뀌면 `sync` 한 번** — 모든 표식의 숫자와 사실 표(`docs/data/corpus_facts.md`)를
   새로 쓴다. CI(`tests/infra/test_corpus_facts.py`)는 `check`와 같은 판정을 돌려 다음 중 하나라도
   있으면 실패한다: 표식이 낡음 · 없는 사실을 가리킴 · 코퍼스 자기 선언이 실제와 다름 · 표식 밖에
   같은 사실의 낡은 값을 손으로 적은 현행 문장.

## 사용

    python3 scripts/analysis/corpus_facts.py show            # 사실 전체 값
    python3 scripts/analysis/corpus_facts.py sync            # 표식·사실 표·자기 선언 갱신
    python3 scripts/analysis/corpus_facts.py check           # 어긋남이 있으면 exit 1

`sync`는 `_provenance.json`의 건수 선언도 실제 값으로 고친다(선언 경로는 `PROVENANCE_DECLARATIONS`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = Path("data/corpus")
FACTS_TABLE = Path("docs/data/corpus_facts.md")
FACTS_JSON = Path("docs/data/corpus_facts.json")  # 테스트·스크립트가 읽는 기계용 사본(같은 값)

FactValue = int | str


@dataclass(frozen=True)
class Fact:
    """사실 하나 — `compute(root)`가 원본에서 값을 센다."""

    desc: str
    source: str  # 원본 파일(저장소 상대 경로) — 사실 표에 출처로 찍는다
    compute: Callable[[Path], FactValue]


# ── 원본 읽기 도우미 ─────────────────────────────────────────────────────────────


_READ_CACHE: dict[tuple[str, int, int], Any] = {}


def _cached(path: Path, parse: Callable[[str], Any]) -> Any:
    """같은 파일을 사실마다 다시 읽지 않는다 — 수정 시각·크기가 바뀌면 다시 읽는다."""
    st = path.stat()
    key = (f"{path}:{parse.__name__}", st.st_mtime_ns, st.st_size)
    if key not in _READ_CACHE:
        _READ_CACHE[key] = parse(path.read_text(encoding="utf-8"))
    return _READ_CACHE[key]


def _parse_jsonl(text: str) -> list[Any]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _json(root: Path, rel: str) -> Any:
    return _cached(root / rel, json.loads)


def _jsonl_count(root: Path, rel: str) -> int:
    return len(_cached(root / rel, _parse_jsonl))


def _list_len(rel: str, key: str) -> Callable[[Path], int]:
    return lambda root: len(_json(root, rel)[key])


def _where_len(rel: str, key: str, field: str, value: str) -> Callable[[Path], int]:
    return lambda root: sum(1 for row in _json(root, rel)[key] if row.get(field) == value)


def _jsonl(rel: str) -> Callable[[Path], int]:
    return lambda root: _jsonl_count(root, rel)


def _jsonl_rows(root: Path, rel: str) -> list[dict[str, Any]]:
    return list(_cached(root / rel, _parse_jsonl))


def _rows(rel: str, key: str | None) -> Callable[[Path], list[dict[str, Any]]]:
    """`key`가 None이면 jsonl 행, 아니면 json 파일의 그 목록."""
    if key is None:
        return lambda root: _jsonl_rows(root, rel)
    return lambda root: list(_json(root, rel)[key])


def _count_if(
    rel: str, key: str | None, pred: Callable[[dict[str, Any]], bool]
) -> Callable[[Path], int]:
    rows = _rows(rel, key)
    return lambda root: sum(1 for r in rows(root) if pred(r))


def _distinct(rel: str, key: str | None, field: str) -> Callable[[Path], int]:
    rows = _rows(rel, key)
    return lambda root: len({r.get(field) for r in rows(root)})


def _sum_len(rel: str, key: str | None, field: str) -> Callable[[Path], int]:
    rows = _rows(rel, key)
    return lambda root: sum(len(r.get(field) or []) for r in rows(root))


def _sha12(rel: str) -> Callable[[Path], str]:
    """줄바꿈을 LF로 통일한 뒤의 sha256 앞 12자 — Windows 체크아웃(CRLF)에서도 같은 값이 나온다."""
    return lambda root: hashlib.sha256(
        (root / rel).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()[:12]


def _problem_banks(root: Path) -> list[Path]:
    """문제은행 = `data/corpus/problem_bank_*/problems.jsonl` 전부(폴더 이름순)."""
    return sorted((root / CORPUS).glob("problem_bank_*/problems.jsonl"))


# ── 사실 목록 ───────────────────────────────────────────────────────────────────

_ATOM = "data/corpus/atom_graph_v1/graph.json"
_MIS = "data/corpus/misconceptions_v1/misconceptions.json"
_STD = "data/corpus/standards_v1/standards.json"


_SCHOOL_LEVELS = (
    ("elementary", "초등"),
    ("middle", "중학"),
    ("high", "고등"),
    ("university", "대학"),
)


def _static_facts() -> dict[str, Fact]:
    f: dict[str, Fact] = {
        # 원자 백본 — 학습 경로·선수 관계의 정본
        "atom_graph.nodes": Fact(
            "원자 백본 노드(세부개념+소단원+단원)", _ATOM, _list_len(_ATOM, "concepts")
        ),
        "atom_graph.atoms": Fact(
            "원자 백본 세부개념", _ATOM, _where_len(_ATOM, "concepts", "level", "세부개념")
        ),
        "atom_graph.subunits": Fact(
            "원자 백본 소단원", _ATOM, _where_len(_ATOM, "concepts", "level", "소단원")
        ),
        "atom_graph.units": Fact(
            "원자 백본 단원", _ATOM, _where_len(_ATOM, "concepts", "level", "단원")
        ),
        "atom_graph.edges": Fact("원자 백본 선수 엣지", _ATOM, _list_len(_ATOM, "edges")),
        "atom_graph.narrative_edges_raw": Fact(
            "원자 백본 서술형 선수 원문", _ATOM, _list_len(_ATOM, "narrative_edges_raw")
        ),
        "atom_graph.sha12": Fact(
            "원자 백본 graph.json sha256 앞 12자(LF 기준)", _ATOM, _sha12(_ATOM)
        ),
        "atom_graph.cross_band_edges_university": Fact(
            "고→대 경계 엣지 원장",
            "data/corpus/atom_graph_v1/cross_band_edges_university_v1.json",
            _list_len("data/corpus/atom_graph_v1/cross_band_edges_university_v1.json", "edges"),
        ),
        "atom_graph.inter_course_edges_university": Fact(
            "대학 과목간 엣지 원장",
            "data/corpus/atom_graph_v1/inter_course_edges_university_v1.json",
            _list_len("data/corpus/atom_graph_v1/inter_course_edges_university_v1.json", "edges"),
        ),
        # 구 개념 그래프(K-12)
        "concept_graph.concepts": Fact(
            "구 개념 그래프 개념",
            "data/corpus/concept_graph_v1/graph.json",
            _list_len("data/corpus/concept_graph_v1/graph.json", "concepts"),
        ),
        "concept_graph.edges": Fact(
            "구 개념 그래프 선수 엣지",
            "data/corpus/concept_graph_v1/graph.json",
            _list_len("data/corpus/concept_graph_v1/graph.json", "edges"),
        ),
        "concept_atom_crosswalk.entries": Fact(
            "개념↔원자 크로스워크 항목",
            "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl",
            _jsonl("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl"),
        ),
        # 오개념
        "misconceptions.count": Fact("오개념(M-id)", _MIS, _list_len(_MIS, "misconceptions")),
        "misconception_crosslinks.count": Fact(
            "오개념 교차 연결",
            "data/corpus/misconception_crosslinks_v1/crosslinks.json",
            _list_len("data/corpus/misconception_crosslinks_v1/crosslinks.json", "crosslinks"),
        ),
        # 성취기준·콘텐츠
        "standards.k12": Fact("K-12 성취기준", _STD, _list_len(_STD, "standards")),
        "standards.k12_links": Fact(
            "K-12 개념↔성취기준 연결",
            "data/corpus/standards_v1/concept_standard_links.json",
            _list_len("data/corpus/standards_v1/concept_standard_links.json", "links"),
        ),
        "standards.university": Fact(
            "대학 성취기준",
            "data/corpus/standards_university_v1/standards.json",
            _list_len("data/corpus/standards_university_v1/standards.json", "standards"),
        ),
        "concept_content.k12": Fact(
            "K-12 개념 콘텐츠",
            "data/corpus/concept_content_v1/content.json",
            _list_len("data/corpus/concept_content_v1/content.json", "content"),
        ),
        "concept_content.university": Fact(
            "대학 개념 콘텐츠",
            "data/corpus/concept_content_university_v1/content.json",
            _list_len("data/corpus/concept_content_university_v1/content.json", "content"),
        ),
        # 작은 그래프·카탈로그
        "skill_graph.skills": Fact(
            "스킬",
            "data/corpus/skill_graph_v1/skills.jsonl",
            _jsonl("data/corpus/skill_graph_v1/skills.jsonl"),
        ),
        "problem_type_graph.types": Fact(
            "문제 유형",
            "data/corpus/problem_type_graph_v1/problem_types.jsonl",
            _jsonl("data/corpus/problem_type_graph_v1/problem_types.jsonl"),
        ),
        "strategy_graph.strategies": Fact(
            "풀이 전략",
            "data/corpus/strategy_graph_v1/strategies.jsonl",
            _jsonl("data/corpus/strategy_graph_v1/strategies.jsonl"),
        ),
        "formula_graph.formulas": Fact(
            "공식",
            "data/corpus/formula_graph_v1/formulas.jsonl",
            _jsonl("data/corpus/formula_graph_v1/formulas.jsonl"),
        ),
        "units.count": Fact(
            "학습 단원 정의(units_v1)",
            "data/corpus/units_v1/*.unit.yaml",
            lambda root: len(list((root / CORPUS / "units_v1").glob("*.unit.yaml"))),
        ),
        "concept_visual_style.entries": Fact(
            "개념 시각화 스타일",
            "data/corpus/concept_visual_style_v1/concept_visual_style.json",
            _list_len("data/corpus/concept_visual_style_v1/concept_visual_style.json", "entries"),
        ),
        # 평가·학습 데이터
        "ai_quality_eval.cases": Fact(
            "AI 품질 평가셋 사례",
            "data/corpus/ai_quality_eval_v1/eval_set.jsonl",
            _jsonl("data/corpus/ai_quality_eval_v1/eval_set.jsonl"),
        ),
        "whs_prm.records": Fact(
            "PRM 단계 라벨 데이터",
            "data/corpus/whs_prm_v0/prm_dataset.jsonl",
            _jsonl("data/corpus/whs_prm_v0/prm_dataset.jsonl"),
        ),
        "problem_variants_staging.records": Fact(
            "문제 변형 대기열",
            "data/corpus/problem_variants_staging_v0/problems.jsonl",
            _jsonl("data/corpus/problem_variants_staging_v0/problems.jsonl"),
        ),
        # 세부 건수 — 코퍼스 자기 선언(_provenance.json)이 적어 둔 것과 대조하려고 둔다
        "atom_graph.university_atoms": Fact(
            "원자 백본 대학 세부개념",
            _ATOM,
            _count_if(
                _ATOM,
                "concepts",
                lambda r: r.get("school_level") == "대학" and r.get("level") == "세부개념",
            ),
        ),
        "atom_graph.prerequisite_total": Fact(
            "원자 백본 선수 관계 전체(원자ID 엣지 + 서술형 원문)",
            _ATOM,
            lambda root: len(_json(root, _ATOM)["edges"])
            + len(_json(root, _ATOM)["narrative_edges_raw"]),
        ),
        **{
            f"atom_graph.nodes_{key}": Fact(
                f"원자 백본 {ko} 노드(전 수준)",
                _ATOM,
                _count_if(_ATOM, "concepts", lambda r, ko=ko: r.get("school_level") == ko),
            )
            for key, ko in _SCHOOL_LEVELS
        },
        **{
            f"atom_graph.atoms_{key}": Fact(
                f"원자 백본 {ko} 세부개념",
                _ATOM,
                _count_if(
                    _ATOM,
                    "concepts",
                    lambda r, ko=ko: r.get("school_level") == ko and r.get("level") == "세부개념",
                ),
            )
            for key, ko in _SCHOOL_LEVELS
            if key
            != "university"  # 대학 세부개념은 atom_graph.university_atoms(자기 선언 키와 같은 이름)
        },
        "atom_graph.atoms_k12": Fact(
            "원자 백본 초·중·고 세부개념",
            _ATOM,
            _count_if(
                _ATOM,
                "concepts",
                lambda r: r.get("school_level") != "대학" and r.get("level") == "세부개념",
            ),
        ),
        "misconceptions.with_ccss": Fact(
            "오개념 중 CCSS 코드가 있는 것",
            _MIS,
            _count_if(_MIS, "misconceptions", lambda r: bool(r.get("ccss_code"))),
        ),
        "misconceptions.with_error_type": Fact(
            "오개념 중 오류 유형이 있는 것",
            _MIS,
            _count_if(_MIS, "misconceptions", lambda r: bool(r.get("error_type"))),
        ),
        "standards.k12_2022": Fact(
            "K-12 성취기준 중 2022 개정",
            _STD,
            _count_if(_STD, "standards", lambda r: r.get("curriculum_revision") == "2022 개정"),
        ),
        "standards.k12_2015": Fact(
            "K-12 성취기준 중 2015 개정",
            _STD,
            _count_if(_STD, "standards", lambda r: r.get("curriculum_revision") == "2015 개정"),
        ),
        "standards.university_links": Fact(
            "대학 개념↔성취기준 연결",
            "data/corpus/standards_university_v1/concept_standard_links.json",
            _list_len("data/corpus/standards_university_v1/concept_standard_links.json", "links"),
        ),
        "standards.university_subjects": Fact(
            "대학 성취기준 과목",
            "data/corpus/standards_university_v1/standards.json",
            _distinct("data/corpus/standards_university_v1/standards.json", "standards", "subject"),
        ),
        "concept_content.k12_flashcards": Fact(
            "K-12 개념 콘텐츠 플래시카드",
            "data/corpus/concept_content_v1/content.json",
            _sum_len("data/corpus/concept_content_v1/content.json", "content", "flashcards"),
        ),
        "concept_content.k12_subjects": Fact(
            "K-12 개념 콘텐츠 과목",
            "data/corpus/concept_content_v1/content.json",
            _distinct("data/corpus/concept_content_v1/content.json", "content", "subject"),
        ),
        "concept_content.university_flashcards": Fact(
            "대학 개념 콘텐츠 플래시카드",
            "data/corpus/concept_content_university_v1/content.json",
            _sum_len(
                "data/corpus/concept_content_university_v1/content.json", "content", "flashcards"
            ),
        ),
        "concept_content.university_subjects": Fact(
            "대학 개념 콘텐츠 과목",
            "data/corpus/concept_content_university_v1/content.json",
            _distinct(
                "data/corpus/concept_content_university_v1/content.json", "content", "subject"
            ),
        ),
        "concept_atom_crosswalk.mapped": Fact(
            "크로스워크 중 원자 코드가 붙은 항목",
            "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl",
            _count_if(
                "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl",
                None,
                lambda r: bool(r.get("atom_codes")),
            ),
        ),
        "skill_graph.families": Fact(
            "스킬 계열",
            "data/corpus/skill_graph_v1/skills.jsonl",
            _distinct("data/corpus/skill_graph_v1/skills.jsonl", None, "family"),
        ),
        "skill_graph.behavior_areas": Fact(
            "스킬 행동 영역",
            "data/corpus/skill_graph_v1/skills.jsonl",
            _distinct("data/corpus/skill_graph_v1/skills.jsonl", None, "behavior_area"),
        ),
        "problem_type_graph.families": Fact(
            "문제 유형 계열",
            "data/corpus/problem_type_graph_v1/problem_types.jsonl",
            _distinct("data/corpus/problem_type_graph_v1/problem_types.jsonl", None, "family"),
        ),
        "strategy_graph.families": Fact(
            "풀이 전략 계열",
            "data/corpus/strategy_graph_v1/strategies.jsonl",
            _distinct("data/corpus/strategy_graph_v1/strategies.jsonl", None, "family"),
        ),
        "formula_graph.families": Fact(
            "공식 계열",
            "data/corpus/formula_graph_v1/formulas.jsonl",
            _distinct("data/corpus/formula_graph_v1/formulas.jsonl", None, "family"),
        ),
        "whs_prm.good": Fact(
            "PRM 라벨 good",
            "data/corpus/whs_prm_v0/prm_dataset.jsonl",
            _count_if(
                "data/corpus/whs_prm_v0/prm_dataset.jsonl", None, lambda r: r.get("label") == "good"
            ),
        ),
        "whs_prm.bad": Fact(
            "PRM 라벨 bad",
            "data/corpus/whs_prm_v0/prm_dataset.jsonl",
            _count_if(
                "data/corpus/whs_prm_v0/prm_dataset.jsonl", None, lambda r: r.get("label") == "bad"
            ),
        ),
        "whs_prm.problems_covered": Fact(
            "PRM 데이터가 덮는 문항",
            "data/corpus/whs_prm_v0/prm_dataset.jsonl",
            _distinct("data/corpus/whs_prm_v0/prm_dataset.jsonl", None, "problem_id"),
        ),
        "ai_quality_eval.hint_cases": Fact(
            "AI 품질 평가셋 힌트 사례",
            "data/corpus/ai_quality_eval_v1/eval_set.jsonl",
            _count_if(
                "data/corpus/ai_quality_eval_v1/eval_set.jsonl",
                None,
                lambda r: r.get("kind") == "hint",
            ),
        ),
        "ai_quality_eval.choice_cases": Fact(
            "AI 품질 평가셋 선택지 사례",
            "data/corpus/ai_quality_eval_v1/eval_set.jsonl",
            _count_if(
                "data/corpus/ai_quality_eval_v1/eval_set.jsonl",
                None,
                lambda r: r.get("kind") == "choice",
            ),
        ),
        # 문제은행 합계
        "problem_bank.banks": Fact(
            "문제은행 수",
            "data/corpus/problem_bank_*/problems.jsonl",
            lambda root: len(_problem_banks(root)),
        ),
        **{
            f"problem_bank.review_{key}": Fact(
                f"문제은행 전체 중 review_status={label}",
                "data/corpus/problem_bank_*/problems.jsonl",
                lambda root, status=status: sum(
                    1
                    for p in _problem_banks(root)
                    for r in _jsonl_rows(root, p.relative_to(root).as_posix())
                    if r.get("review_status") == status
                ),
            )
            for key, status, label in (
                ("unset", None, "없음"),
                ("approved", "approved", "approved"),
                ("pending", "pending", "pending"),
            )
        },
        "problem_bank.total": Fact(
            "문제은행 전체 문항",
            "data/corpus/problem_bank_*/problems.jsonl",
            lambda root: sum(
                _jsonl_count(root, p.relative_to(root).as_posix()) for p in _problem_banks(root)
            ),
        ),
    }
    return f


def build_facts(root: Path = ROOT) -> dict[str, Fact]:
    """정적 사실 + 문제은행별 사실(폴더를 발견하는 대로 늘어난다)."""
    facts = _static_facts()
    for path in _problem_banks(root):
        name = path.parent.name.removeprefix("problem_bank_")
        rel = path.relative_to(root).as_posix()
        facts[f"problem_bank.{name}"] = Fact(f"문제은행 {path.parent.name}", rel, _jsonl(rel))
    return facts


def compute_all(root: Path = ROOT, facts: dict[str, Fact] | None = None) -> dict[str, FactValue]:
    facts = build_facts(root) if facts is None else facts
    return {fid: fact.compute(root) for fid, fact in facts.items()}


# ── 코퍼스 자기 선언(_provenance.json) ───────────────────────────────────────────

# (provenance 파일, 키 경로, 사실 이름) — 선언이 실제와 다르면 check 실패 · sync가 고친다
PROVENANCE_DECLARATIONS: list[tuple[str, tuple[str, ...], str]] = [
    ("atom_graph_v1", ("node_counts", "total"), "atom_graph.nodes"),
    ("atom_graph_v1", ("node_counts", "atoms"), "atom_graph.atoms"),
    ("atom_graph_v1", ("node_counts", "subunits"), "atom_graph.subunits"),
    ("atom_graph_v1", ("node_counts", "units"), "atom_graph.units"),
    ("atom_graph_v1", ("edge_counts", "atom_id_edges"), "atom_graph.edges"),
    ("atom_graph_v1", ("edge_counts", "narrative_edges_raw"), "atom_graph.narrative_edges_raw"),
    ("atom_graph_v1", ("school_level_university_atoms",), "atom_graph.university_atoms"),
    ("misconceptions_v1", ("counts", "misconceptions"), "misconceptions.count"),
    ("misconceptions_v1", ("counts", "with_ccss"), "misconceptions.with_ccss"),
    ("misconceptions_v1", ("counts", "with_error_type"), "misconceptions.with_error_type"),
    ("concept_atom_crosswalk_v1", ("counts", "mapped"), "concept_atom_crosswalk.mapped"),
    ("standards_v1", ("counts", "2022 개정"), "standards.k12_2022"),
    ("standards_v1", ("counts", "2015 개정"), "standards.k12_2015"),
    ("standards_university_v1", ("counts", "links"), "standards.university_links"),
    ("standards_university_v1", ("counts", "subjects"), "standards.university_subjects"),
    ("concept_content_v1", ("counts", "flashcards"), "concept_content.k12_flashcards"),
    ("concept_content_v1", ("counts", "subjects"), "concept_content.k12_subjects"),
    (
        "concept_content_university_v1",
        ("counts", "flashcards"),
        "concept_content.university_flashcards",
    ),
    (
        "concept_content_university_v1",
        ("counts", "subjects"),
        "concept_content.university_subjects",
    ),
    ("skill_graph_v1", ("counts", "families"), "skill_graph.families"),
    ("skill_graph_v1", ("counts", "behavior_areas"), "skill_graph.behavior_areas"),
    ("problem_type_graph_v1", ("counts", "families"), "problem_type_graph.families"),
    ("strategy_graph_v1", ("counts", "families"), "strategy_graph.families"),
    ("formula_graph_v1", ("counts", "families"), "formula_graph.families"),
    ("whs_prm_v0", ("label_counts", "good"), "whs_prm.good"),
    ("whs_prm_v0", ("label_counts", "bad"), "whs_prm.bad"),
    ("whs_prm_v0", ("problems_covered",), "whs_prm.problems_covered"),
    ("ai_quality_eval_v1", ("counts", "hint_cases"), "ai_quality_eval.hint_cases"),
    ("ai_quality_eval_v1", ("counts", "choice_cases"), "ai_quality_eval.choice_cases"),
    ("misconception_crosslinks_v1", ("counts", "crosslinks"), "misconception_crosslinks.count"),
    ("concept_atom_crosswalk_v1", ("counts", "entries"), "concept_atom_crosswalk.entries"),
    ("standards_v1", ("counts", "standards"), "standards.k12"),
    ("standards_v1", ("counts", "links"), "standards.k12_links"),
    ("standards_university_v1", ("counts", "standards"), "standards.university"),
    ("concept_content_v1", ("counts", "content"), "concept_content.k12"),
    ("concept_content_university_v1", ("counts", "content"), "concept_content.university"),
    ("skill_graph_v1", ("counts", "skills"), "skill_graph.skills"),
    ("problem_type_graph_v1", ("counts", "problem_types"), "problem_type_graph.types"),
    ("strategy_graph_v1", ("counts", "strategies"), "strategy_graph.strategies"),
    ("formula_graph_v1", ("counts", "formulas"), "formula_graph.formulas"),
    ("units_v1", ("counts", "units"), "units.count"),
    ("concept_visual_style_v1", ("record_count",), "concept_visual_style.entries"),
    ("ai_quality_eval_v1", ("counts", "cases"), "ai_quality_eval.cases"),
    ("whs_prm_v0", ("record_count",), "whs_prm.records"),
    ("problem_variants_staging_v0", ("record_count",), "problem_variants_staging.records"),
]


Declarations = list[tuple[str, tuple[str, ...], str]]


def _provenance_declarations(root: Path) -> Declarations:
    """정적 선언 + 문제은행마다 `record_count`."""
    out = list(PROVENANCE_DECLARATIONS)
    for path in _problem_banks(root):
        name = path.parent.name
        out.append((name, ("record_count",), f"problem_bank.{name.removeprefix('problem_bank_')}"))
    return out


def _dig(obj: Any, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def provenance_mismatches(
    root: Path, values: dict[str, FactValue], declarations: Declarations | None = None
) -> list[str]:
    """자기 선언이 실제와 다른 곳(선언 키가 사라진 것도 어긋남이다)."""
    out: list[str] = []
    decls = _provenance_declarations(root) if declarations is None else declarations
    for corpus, keys, fid in decls:
        rel = CORPUS / corpus / "_provenance.json"
        declared = _dig(_json(root, str(rel)), keys)
        if declared != values[fid]:
            out.append(f"{rel} {'.'.join(keys)}={declared} ≠ 실제 {values[fid]} ({fid})")
    return out


def _set_in(obj: dict[str, Any], keys: tuple[str, ...], value: FactValue) -> None:
    for k in keys[:-1]:
        obj = obj[k]
    obj[keys[-1]] = value


def sync_provenance(
    root: Path, values: dict[str, FactValue], declarations: Declarations | None = None
) -> list[str]:
    """어긋난 자기 선언을 실제 값으로 고친다 — 키 순서·들여쓰기(2칸)·한글을 보존한다."""
    changed: list[str] = []
    by_file: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    decls = _provenance_declarations(root) if declarations is None else declarations
    for corpus, keys, fid in decls:
        by_file.setdefault(corpus, []).append((keys, fid))
    for corpus, items in by_file.items():
        path = root / CORPUS / corpus / "_provenance.json"
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        dirty = False
        for keys, fid in items:
            if _dig(data, keys) != values[fid]:
                if _dig(data, keys[:-1]) is None and len(keys) > 1:
                    raise SystemExit(f"{path}: 선언 경로 {'.'.join(keys)}가 없다 — 손으로 확인하라")
                _set_in(data, keys, values[fid])
                dirty = True
        if dirty:
            newline = "\n" if raw.endswith("\n") else ""
            if json.dumps(json.loads(raw), ensure_ascii=False, indent=2) + newline != raw:
                # 다시 쓰면 건수 말고 서식까지 바뀌는 파일 — 조용히 재서식하지 않고 사람에게 넘긴다
                raise SystemExit(
                    f"{path}: 2칸 들여쓰기 JSON이 아니라 자동 갱신하지 않는다"
                    " — 건수만 손으로 고쳐라"
                )
            text = json.dumps(data, ensure_ascii=False, indent=2) + newline
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root).as_posix())
    return changed


# ── 문서 표식 ───────────────────────────────────────────────────────────────────

MARKER = re.compile(r"<!-- fact:(?P<id>[a-z0-9_.]+)(?P<raw> raw)? -->(?P<shown>.*?)<!-- /fact -->")


def format_value(value: FactValue, raw: bool) -> str:
    if isinstance(value, int) and not raw:
        return f"{value:,}"
    return str(value)


def _markdown_files(root: Path) -> Iterator[Path]:
    """표식을 찾는 범위 — 저장소의 마크다운 전부(.git·node_modules·빌드 산출물 제외)."""
    skip = {".git", "node_modules", "build", ".dart_tool", ".venv", "venv"}
    for path in sorted(root.rglob("*.md")):
        if skip.intersection(path.relative_to(root).parts):
            continue
        yield path


@dataclass(frozen=True)
class MarkerHit:
    path: str
    line: int
    fact_id: str
    shown: str
    expected: str | None  # None = 없는 사실 이름


def scan_markers(root: Path, values: dict[str, FactValue]) -> list[MarkerHit]:
    hits: list[MarkerHit] = []
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8")
        if "<!-- fact:" not in text:
            continue
        for m in MARKER.finditer(text):
            fid = m.group("id")
            expected = format_value(values[fid], bool(m.group("raw"))) if fid in values else None
            line = text.count("\n", 0, m.start()) + 1
            hits.append(
                MarkerHit(path.relative_to(root).as_posix(), line, fid, m.group("shown"), expected)
            )
    return hits


def unclosed_markers(root: Path) -> list[str]:
    """여는 표식 수와 닫는 표식 수가 다르면 정규식이 조용히 건너뛴다 — 그 자체를 실패로 본다."""
    out: list[str] = []
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8")
        opens = len(re.findall(r"<!-- fact:", text))
        if opens and opens != len(MARKER.findall(text)):
            out.append(
                f"{path.relative_to(root)}: 여는 표식 {opens}개 중"
                f" 짝이 맞는 것 {len(MARKER.findall(text))}개"
            )
    return out


def sync_markers(root: Path, values: dict[str, FactValue]) -> list[str]:
    changed: list[str] = []
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8")
        if "<!-- fact:" not in text:
            continue

        def _sub(m: re.Match[str]) -> str:
            fid = m.group("id")
            if fid not in values:
                return m.group(0)  # 없는 사실은 check가 실패로 보고한다 — 여기서 지우지 않는다
            raw = m.group("raw") or ""
            return f"<!-- fact:{fid}{raw} -->{format_value(values[fid], bool(raw))}<!-- /fact -->"

        new = MARKER.sub(_sub, text)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root).as_posix())
    return changed


# ── 사실 표(생성 문서) ──────────────────────────────────────────────────────────


def render_table(root: Path, facts: dict[str, Fact] | None = None) -> str:
    facts = build_facts(root) if facts is None else facts
    values = {fid: f.compute(root) for fid, f in facts.items()}
    lines = [
        "# 코퍼스 사실 표 (생성 문서 — 손으로 고치지 않는다)",
        "",
        "> 이 파일은 `python3 scripts/analysis/corpus_facts.py sync`가 만든다."
        " 값은 원본 파일에서 센 것이다.",
        "> 문서에서 이 값을 인용할 때는 숫자를 손으로 적지 말고 사실 이름으로 표식을 단다"
        " — 표식 형식·규칙은 `scripts/analysis/corpus_facts.py` 모듈 설명(태스크 OPS-154).",
        "",
        "| 사실 이름 | 값 | 설명 | 원본 |",
        "|---|---:|---|---|",
    ]
    for fid in sorted(facts):
        lines.append(
            f"| `{fid}` | {format_value(values[fid], False)} | {facts[fid].desc}"
            f" | `{facts[fid].source}` |"
        )
    return "\n".join(lines) + "\n"


def render_json(root: Path, facts: dict[str, Fact] | None = None) -> str:
    """기계용 사실 표 — 테스트는 건수를 손으로 박지 않고 이 파일에서 읽는다."""
    values = compute_all(root, facts)
    return json.dumps(dict(sorted(values.items())), ensure_ascii=False, indent=2) + "\n"


def load_facts_json(root: Path = ROOT) -> dict[str, FactValue]:
    """커밋된 기계용 사실 표를 읽는다(원본을 다시 세지 않는다 — 신선도는 check가 보증)."""
    data: dict[str, FactValue] = json.loads((root / FACTS_JSON).read_text(encoding="utf-8"))
    return data


# ── 표식 밖 손 기입 탐지 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Phrase:
    """사실을 말하는 표기 하나. `n` 그룹이 숫자이고, `accepts`의 사실 값 중 하나와 같아야 한다.

    같은 표기가 여러 사실을 가리킬 수 있어(예: '엣지 N'은 원자 백본·구 개념 그래프·서술형 원문
    모두) 받아들이는 값을 사실 이름 묶음으로 둔다. 어느 값과도 다르면 낡은 값이다.
    """

    label: str
    pattern: re.Pattern[str]
    accepts: tuple[str, ...]
    min_value: int = 100  # 이보다 작은 수는 사실 건수가 아니라 예시·순번일 가능성이 커 보지 않는다


# 받아들이는 값에서 이 비율 안쪽에 있는데 같지 않으면 '같은 사실의 낡은 값'으로 본다. 더 멀면 다른
# 것(부분 집합·다른 지표·예시)을 센 숫자라 이 사실의 언급으로 보지 않는다 — 예: '코퍼스 1,616건'은
# 문제은행 일부를 센 것이지 전체(14,742)의 옛 값이 아니다.
NEAR_RATIO = 0.10  # 실측된 낡은 값은 모두 8% 안쪽(541↔581이 최대) — 넓히면 다른 지표를 잡는다


_N = r"\**(?P<n>\d{1,3}(?:,\d{3})+|\d{3,6})\**"  # 쉼표 있는 수 또는 3~6자리 수(굵게 표시 허용)

_EDGE_FACTS = (
    "atom_graph.edges",
    "atom_graph.prerequisite_total",
    "atom_graph.narrative_edges_raw",
    "concept_graph.edges",
)
_NODE_FACTS = (
    "atom_graph.nodes",
    "atom_graph.atoms",
    "atom_graph.subunits",
    "atom_graph.nodes_elementary",
    "atom_graph.nodes_middle",
    "atom_graph.nodes_high",
    "atom_graph.nodes_university",
    "concept_graph.concepts",
)
_ATOM_FACTS = (
    "atom_graph.atoms",
    "atom_graph.nodes",
    "atom_graph.atoms_elementary",
    "atom_graph.atoms_middle",
    "atom_graph.atoms_high",
    "atom_graph.university_atoms",
    "atom_graph.atoms_k12",
    "atom_graph.nodes_university",
)
_MIS_FACTS = ("misconceptions.count", "misconceptions.with_ccss", "misconceptions.with_error_type")
_STD_FACTS = (
    "standards.k12",
    "standards.k12_2022",
    "standards.k12_2015",
    "standards.k12_links",
    "standards.university",
    "standards.university_links",
)

PHRASES: list[Phrase] = [
    Phrase(
        "N노드·M엣지의 노드", re.compile(_N + r"\s*노드\s*[·,/]\s*\d[\d,]*\s*엣지"), _NODE_FACTS
    ),
    Phrase(
        "N노드·M엣지의 엣지",
        re.compile(r"\d[\d,]*\s*노드\s*[·,/]\s*" + _N + r"\s*엣지"),
        _EDGE_FACTS,
    ),
    Phrase("N엣지·N 선수엣지", re.compile(_N + r"\s*(?:선수\s*)?엣지"), _EDGE_FACTS),
    Phrase(
        "엣지 N·선수엣지 N·원자ID 엣지 N",
        re.compile(r"(?:원자ID\s*|선수\s*)?엣지\s*(?:는|은|가|이)?\s*" + _N),
        _EDGE_FACTS,
    ),
    Phrase(
        "원자 N·세부개념 N·원자 리프 N",
        re.compile(r"(?:원자|세부개념|원자\s*리프)\s*\(?" + _N),
        _ATOM_FACTS,
    ),
    Phrase("N개 원자·N 원자", re.compile(_N + r"\s*(?:개\s*)?원자(?!\s*백본)"), _ATOM_FACTS),
    Phrase("원자 백본 N", re.compile(r"원자\s*백본\s*\(?" + _N), ("atom_graph.nodes",)),
    Phrase("N 노드(4자리 이상)", re.compile(r"(?P<n>\d{1,3},\d{3}|\d{4,6})\s*노드"), _NODE_FACTS),
    Phrase(
        "서술형 N", re.compile(r"서술형\s*(?:raw\s*)?\(?" + _N), ("atom_graph.narrative_edges_raw",)
    ),
    Phrase(
        "오개념 N·M-id N",
        re.compile(r"(?:오개념|M-id)\s*(?:카탈로그\s*)?\(?" + _N + r"(?!\s*(?:확장\s*)?트랜치)"),
        _MIS_FACTS,
    ),
    Phrase("성취기준 N", re.compile(r"성취기준\s*\(?" + _N), _STD_FACTS),
    Phrase(
        "문제은행·코퍼스 N건/문항",
        re.compile(
            r"(?:문제은행|은행|코퍼스)[^\n|]{0,24}?(?P<n>\d{1,2},\d{3}|\d{5})\s*(?:건|문항|문|행)"
        ),
        ("problem_bank.total", "problem_bank.review_unset", "problem_bank.review_approved"),
        min_value=1000,
    ),
    Phrase(
        "N문항(4자리 이상)",
        re.compile(r"(?P<n>\d{1,2},\d{3}|\d{5})\s*문항"),
        ("problem_bank.total", "problem_bank.review_unset", "problem_bank.review_approved"),
        min_value=1000,
    ),
]

# 시점 기록 — 그 시점 값을 적는 곳이라 낡은 값이 있어도 정상이다. 통째로 범위 밖.
HISTORY_GLOBS: tuple[str, ...] = (
    "MEMORY.md",
    "backlog/**",
    # 읽기 전용(헌법 제9조) — 정정은 docs/constitution_proposals/ 초안으로 Kiki가 한다
    "constitution/**",
    "docs/constitution_proposals/**",
    "docs/reviews/**",
    "docs/handoff/**",
    "docs/strategy/**",
    "docs/**/*review*.md",
    "docs/**/*_adr.md",
    "docs/**/*audit*.md",
    "docs/**/*20[0-9][0-9]-[0-9][0-9]*",  # 파일·폴더 이름에 날짜가 있는 보고서
    "docs/**/*20[0-9][0-9]-Q[1-4]*",  # 분기 보고서
    "docs/data/ai_review_*.md",
    "src/backend/alembic/versions/**",
    "tests/fixtures/**",
    FACTS_TABLE.as_posix(),
    FACTS_JSON.as_posix(),
    "scripts/analysis/corpus_facts.py",
    "tests/infra/test_corpus_facts.py",
)

# 줄 단위 시점 표지 — 날짜·이력 화살표·'당시/이전'·정정 기록·커밋 기준·취소선
_DATED = re.compile(
    r"20\d\d-\d\d(?:-\d\d)?|→|->|당시|이전|직전|시점|착수\s*전|구\s*\d|\(구|~~|정정|"
    r"main\s+[0-9a-f]{7,}|KG-\d|S4-60|실측\s*\(|과거|옛\s|기존\s*값|원천\s*\d|업로드"
)

# 스캔 범위 — 현행 상태를 말할 수 있는 곳 전부(코드 주석·docstring 포함)
SCAN_GLOBS: tuple[str, ...] = (
    "*.md",
    "docs/**/*.md",
    "src/**/*.py",
    "scripts/**/*.py",
    "tests/**/*.py",
    ".github/**/*.yml",
    "pipeline.yaml",
    "data/*.json",
)


def _is_history(rel: str) -> bool:
    from fnmatch import fnmatch

    return any(
        fnmatch(rel, g) or (g.endswith("/**") and rel.startswith(g[:-3] + "/"))
        for g in HISTORY_GLOBS
    )


def _scan_files(root: Path) -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            rel = path.relative_to(root)
            if {"node_modules", ".venv", "venv", "__pycache__", ".dart_tool"}.intersection(
                rel.parts
            ):
                continue
            seen.add(path)
            if not _is_history(rel.as_posix()):
                yield path


def _current_state_files(root: Path) -> Iterator[Path]:
    """마크다운 현행 문서 — 현재 값도 표식으로 달아야 한다(원본이 바뀌면 sync가 따라간다)."""
    return (p for p in _scan_files(root) if p.suffix == ".md")


def _to_int(text: str) -> int:
    return int(text.replace(",", ""))


@dataclass(frozen=True)
class Mention:
    path: str
    line: int
    text: str
    value: int
    label: str
    stale: bool  # True = 받아들이는 사실 값 어디에도 없다
    markable: bool  # 마크다운 본문(코드 블록·인라인 코드 밖) — 표식으로 바꿀 수 있다


def find_mentions(root: Path, values: dict[str, FactValue]) -> list[Mention]:
    out: list[Mention] = []
    for path in _scan_files(root):
        rel = path.relative_to(root).as_posix()
        is_md = path.suffix == ".md"
        in_fence = False
        prev_dated = False
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if is_md and line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            body = MARKER.sub("", line)
            dated = bool(_DATED.search(body))
            # 줄바꿈된 한 문장: 바로 윗줄에 시점 표지가 있으면 이 줄도 그 시점의 기록이다
            if dated or (prev_dated and body.strip()):
                prev_dated = dated
                continue
            prev_dated = False
            code_spans = [m.span() for m in re.finditer(r"`[^`]*`", body)] if is_md else []
            seen_spans: set[tuple[int, int]] = set()
            for ph in PHRASES:
                for m in ph.pattern.finditer(body):
                    span = m.span("n")
                    if span in seen_spans:
                        continue
                    raw_n = m.group("n")
                    value = _to_int(raw_n)
                    if value < ph.min_value or ("," not in raw_n and 1900 <= value <= 2099):
                        continue  # 작은 수·연도(2015 개정·2022 개정)는 건수가 아니다
                    ok = {v for f in ph.accepts if isinstance(v := values.get(f), int)}
                    if value not in ok and not any(abs(value - v) <= v * NEAR_RATIO for v in ok):
                        continue  # 이 사실의 언급이 아니다(부분 집합·다른 지표)
                    seen_spans.add(span)
                    in_code = any(a <= span[0] < b for a, b in code_spans)
                    out.append(
                        Mention(
                            rel,
                            no,
                            m.group(0).strip(),
                            value,
                            ph.label,
                            stale=value not in ok,
                            markable=is_md and not in_fence and not in_code,
                        )
                    )
    return out


def unmarked_phrases(root: Path, values: dict[str, FactValue] | None = None) -> list[str]:
    """낡은 손 기입(어디서든) + 마크다운 본문의 표식 없는 현재 값."""
    values = compute_all(root) if values is None else values
    out: list[str] = []
    for m in find_mentions(root, values):
        if m.stale:
            out.append(
                f"{m.path}:{m.line} 낡은 값 '{m.text}' ({m.label})"
                " — 현재 값으로 고치거나 시점을 밝힌다"
            )
        elif m.markable:
            out.append(f"{m.path}:{m.line} 표식 없는 '{m.text}' ({m.label}) — 표식으로 바꾼다")
    return out


# ── 테스트의 손 고정값 탐지 ──────────────────────────────────────────────────────

# 테스트 코드(주석·문자열 제외)의 숫자 리터럴이 코퍼스 사실 값과 같으면 손으로 박은 고정값이다.
# 테스트는 `docs/data/corpus_facts.json`에서 읽어야 한다 — 원본이 바뀌면 sync 한 번으로 따라간다.
# 흔한 수(백 단위 · HTTP 상태 코드)는 우연히 같을 수 있어 보지 않는다.
PIN_SCAN_GLOBS: tuple[str, ...] = ("tests/**/*.py",)
PIN_MIN_VALUE = 400
_COMMON_NUMBERS = frozenset({400, 401, 403, 404, 405, 409, 410, 415, 422, 429, 500, 502, 503, 504})
PIN_ALLOW = re.compile(r"#\s*corpus-pin:\s*\S")  # 같은 줄에 사유를 달면 허용(합성 픽스처·시점 고정)


def distinctive_values(values: dict[str, FactValue]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for fid, v in values.items():
        if isinstance(v, int) and v >= PIN_MIN_VALUE and v % 100 and v not in _COMMON_NUMBERS:
            out.setdefault(v, []).append(fid)
    return out


def hand_pins(root: Path, values: dict[str, FactValue] | None = None) -> list[str]:
    import io
    import tokenize

    values = compute_all(root) if values is None else values
    wanted = distinctive_values(values)
    out: list[str] = []
    seen: set[Path] = set()
    for pattern in PIN_SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file() or _is_history(path.relative_to(root).as_posix()):
                continue
            seen.add(path)
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            try:
                tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            except (tokenize.TokenError, SyntaxError):
                continue
            for tok in tokens:
                if tok.type != tokenize.NUMBER:
                    continue
                try:
                    num = int(tok.string.replace("_", ""), 0)
                except ValueError:
                    continue
                if num in wanted and not PIN_ALLOW.search(lines[tok.start[0] - 1]):
                    out.append(
                        f"{path.relative_to(root)}:{tok.start[0]} 손 고정값 {tok.string}"
                        f" ({'·'.join(wanted[num])}) — corpus_facts.json에서 읽는다"
                    )
    return out


# ── 판정 ────────────────────────────────────────────────────────────────────────


def check(
    root: Path = ROOT,
    facts: dict[str, Fact] | None = None,
    declarations: Declarations | None = None,
) -> list[str]:
    facts = build_facts(root) if facts is None else facts
    values = compute_all(root, facts)
    problems: list[str] = []
    problems += provenance_mismatches(root, values, declarations)
    problems += unclosed_markers(root)
    hits = scan_markers(root, values)
    for h in hits:
        if h.expected is None:
            problems.append(f"{h.path}:{h.line} 없는 사실 이름 '{h.fact_id}'")
        elif h.shown != h.expected:
            problems.append(
                f"{h.path}:{h.line} {h.fact_id} 표식 값 {h.shown!r} ≠ 실제 {h.expected!r}"
            )
    table = root / FACTS_TABLE
    if not table.is_file() or table.read_text(encoding="utf-8") != render_table(root, facts):
        problems.append(f"{FACTS_TABLE} 가 원본과 다르다(생성 문서) — sync 필요")
    fj = root / FACTS_JSON
    if not fj.is_file() or fj.read_text(encoding="utf-8") != render_json(root, facts):
        problems.append(f"{FACTS_JSON} 가 원본과 다르다(생성 문서) — sync 필요")
    problems += unmarked_phrases(root, values)
    problems += hand_pins(root, values)
    return problems


def sync(
    root: Path = ROOT,
    facts: dict[str, Fact] | None = None,
    declarations: Declarations | None = None,
) -> list[str]:
    facts = build_facts(root) if facts is None else facts
    values = compute_all(root, facts)
    changed = sync_provenance(root, values, declarations) + sync_markers(root, values)
    table = root / FACTS_TABLE
    rendered = render_table(root, facts)
    if not table.is_file() or table.read_text(encoding="utf-8") != rendered:
        table.write_text(rendered, encoding="utf-8", newline="\n")
        changed.append(str(FACTS_TABLE))
    fj = root / FACTS_JSON
    rendered_json = render_json(root, facts)
    if not fj.is_file() or fj.read_text(encoding="utf-8") != rendered_json:
        fj.write_text(rendered_json, encoding="utf-8", newline="\n")
        changed.append(str(FACTS_JSON))
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="코퍼스 사실 단일 원천 (OPS-154)")
    ap.add_argument("command", choices=["show", "sync", "check"])
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.command == "show":
        for fid, value in sorted(compute_all(root).items()):
            print(f"{fid}\t{format_value(value, False)}")
        return 0
    if args.command == "sync":
        changed = sync(root)
        print("갱신한 파일:" if changed else "갱신할 파일 없음 — 이미 원본과 같다")
        for c in changed:
            print(f"  {c}")
        return 0
    problems = check(root)
    for p in problems:
        print(f"✘ {p}")
    markers = len(scan_markers(root, compute_all(root)))
    print(
        f"코퍼스 사실 {len(build_facts(root))}개 · 문서 표식 {markers}개 · 어긋남 {len(problems)}건"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
