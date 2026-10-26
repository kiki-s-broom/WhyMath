"""거버넌스 감지 — 플레이북 Part 2 §1 "노드 = 독립 오개념 발생 단위" 입도 동결.

법칙: 노드 입도는 "함수"(너무 큼)도 "기울기의 x증가량"(폭발/과세분)도 아닌 **독립적으로
오개념이 발생·진단·교정되는 최소 단위**여야 한다.

이 테스트는 *측정·동결*만 한다(재분할하지 않는다 — 대규모 재분할은 전문가 검수 소관,
docs/architecture/concept_node_layering_decision.md §입도). build_checkpoint_questions.md 단계3이
최우선 리스크로 지목한 **이중 truth source**(개념그래프 vs 원자그래프)를 코드로 가시화한다:

  ① **이중 truth source 카운트 동결**: concept_graph_v1·atom_graph_v1 노드 수를 스냅샷으로
     고정 — 무단 재분할·중복 증식으로 수가 예기치 않게 변하면 red(의식적 리뷰 강제). 고정 지점은
     `docs/data/corpus_facts.json`(OPS-154)이며, 그 파일의 diff가 의식적 리뷰 지점이다.
  ② **입도 순서 sanity**: 원자그래프가 개념그래프보다 *세분*이다(atom > concept).
  ③ **오개념 발생 단위 불변식(핵심)**: 원자그래프 '세부개념' 레벨 노드는 *전부* 독립 오개념
     (`misconception`)을 보유한다 — 즉 세부개념 원자는 Part 2 §1 법칙("독립 오개념 발생 단위")을
     만족한다. 과세분(오개념 없는 세부 노드)이 유입되면 이 100% 커버리지가 깨져 red가 된다.

hermetic: 코퍼스 JSON 읽기만(DB·네트워크 불요).
"""

from __future__ import annotations

import json
from pathlib import Path

# 리포지토리 루트(tests/backend/l1/ 기준 3단 상위) → 코퍼스 경로.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPT_GRAPH = _REPO_ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_ATOM_GRAPH = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 동결 스냅샷(2026-07-02 기준·Part 2 검토 — 당시 437·2,683). 값이 바뀌면 *의식적으로* 갱신하라 —
# 무단 재분할/중복 증식/누락을 잡는 회귀 가드다(단일 진실 원천 붕괴 감지).
# 고정 지점(OPS-154): 손 숫자가 아니라 `docs/data/corpus_facts.json`에서 읽는다. 코퍼스가 바뀌면
# `corpus_facts.py sync`가 그 파일을 갱신하고, *그 파일의 diff*가 의식적 리뷰 지점이 된다.
# 관점(2026-07-04·S0-4b): 구 437 개념그래프는 `legacy_snapshot`으로 격하됐고 원자 2,683이
# runtime truth source다. 여기서는 *카운트 스냅샷만* 동결한다(값·로직 불변). 격하 자체의 회귀
# 가드는 `test_legacy_snapshot_governance.py` 소관.
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)
_EXPECTED_CONCEPT_NODES = _FACTS["concept_graph.concepts"]
_EXPECTED_ATOM_NODES = _FACTS["atom_graph.nodes"]
_ATOM_DETAIL_LEVEL = "세부개념"


def _load_nodes(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("concepts", [])
    assert isinstance(nodes, list)
    return nodes


def _nonempty(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def test_dual_truth_source_counts_frozen() -> None:
    """개념그래프·원자그래프 노드 수 스냅샷 동결(이중 truth source 가시화·무단 변동 감지)."""
    concept_nodes = _load_nodes(_CONCEPT_GRAPH)
    atom_nodes = _load_nodes(_ATOM_GRAPH)
    assert len(concept_nodes) == _EXPECTED_CONCEPT_NODES, (
        f"개념그래프 노드 수가 {_EXPECTED_CONCEPT_NODES}→{len(concept_nodes)}로 바뀌었다. "
        "무단 재분할/중복이 아닌지 확인하고, 정당하면 corpus_facts.py sync로 사실 파일을 갱신하라."
    )
    assert len(atom_nodes) == _EXPECTED_ATOM_NODES, (
        f"원자그래프 노드 수가 {_EXPECTED_ATOM_NODES}→{len(atom_nodes)}로 바뀌었다. "
        "'기울기의 x증가량' 급 과세분이 유입되지 않았는지 확인하라(Part 2 §1)."
    )


def test_atom_graph_is_finer_than_concept_graph() -> None:
    """입도 순서 sanity — 원자그래프가 개념그래프보다 세분이다(원자 > 개념)."""
    assert len(_load_nodes(_ATOM_GRAPH)) > len(_load_nodes(_CONCEPT_GRAPH))


def test_detail_atoms_are_independent_misconception_units() -> None:
    """세부개념 원자는 *전부* 독립 오개념을 보유한다 — Part 2 §1 법칙 100% 충족(과세분 0).

    오개념 없는 세부 노드가 유입되면 "독립 오개념 발생 단위"가 아니므로 과세분 후보다 → red.
    """
    atoms = _load_nodes(_ATOM_GRAPH)
    detail = [a for a in atoms if a.get("level") == _ATOM_DETAIL_LEVEL]
    assert detail, "세부개념 레벨 원자가 있어야 한다"
    without_misconception = [a for a in detail if not _nonempty(a.get("misconception"))]
    assert not without_misconception, (
        f"세부개념 원자 {len(without_misconception)}/{len(detail)}개가 "
        "독립 오개념(misconception)을 "
        "갖지 않는다 — 과세분(Part 2 §1 '기울기의 x증가량') 후보다. 오개념 없는 세부 노드는 개념 "
        "속성으로 흡수하거나 상위 노드로 병합하라."
    )
