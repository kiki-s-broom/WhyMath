"""거버넌스 동결 — 구 437 개념그래프 = legacy_snapshot 격하(S0-4b/4c) 3불변식.

배경: runtime truth source가 **원자 백본(atom_graph_v1)** 단일로 확정되면서, 구 437 개념그래프
(`concept_node`·`concept_embedding`·`ConceptNodeMeta`·`fetch_node_meta`·`search_concepts`)는
`legacy_snapshot {readonly, non_runtime, audit_only}`로 *형식 격하*됐다(물리 삭제 0). 선행 완료:
S0-4a(`/concepts/search`→`search_atoms`)·S0-4d(L2 enrich→`fetch_atom_node_meta`).

이 테스트는 `test_embedding_namespace_governance.py`·`test_node_granularity_governance.py`의 정적
스캔 거버넌스 패턴을 미러링해 **3불변식을 동결**한다(hermetic — 소스 텍스트·코퍼스 JSON 스캔만·
DB/네트워크 0):

  (i)  **런타임 437 reader = 0**: `whymath_backend/{api,l2,l3,l4}` 소스를 **AST**로 파싱해, 구 437
       data-reader 심볼의 *실제* import/참조(주석·docstring·문자열 제외)가 0건임을 단언한다. 신규
       런타임 reader가 유입되면 red. (오탐 방지: `search_concepts_endpoint`[핸들러명]·docstring
       prose는 AST 식별자/문 기준이라 잡히지 않는다.)
  (ii) **audit/빌드타임 화이트리스트**: 구 437을 읽어도 되는 소비처는 `l1/concept_atom_crosswalk`·
       `l1/curriculum/populate.py`뿐이다(빌드타임 provenance·이전 근거). 이 화이트리스트를 상수로
       동결 — 목록 밖 모듈이 구 437 코퍼스/심볼을 읽으면 red.
  (iii)**lifecycle 마커 존재**: 코퍼스 `_provenance.json`의 `lifecycle.status == "legacy_snapshot"`·
       `lifecycle.non_runtime is True`. 격하 표식이 지워지면 red.

주의: 공유 sync-엔진 빌더 `_build_sync_engine`(구 437 `embedding.py`에 물리적으로 거주하나 원자·
기타 L1 projection이 재사용하는 *인프라* 유틸)은 개념 *데이터* read가 아니므로 reader 심볼에서
제외한다. (i)은 concept_graph 패키지 import 자체를 금지하지만 api/l2/l3/l4는 이 유틸도 import하지
않으므로 여전히 0이다.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

# 리포지토리 루트(tests/backend/l1/ 기준 3단 상위) → backend 패키지·코퍼스 경로.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PKG_ROOT = _REPO_ROOT / "src" / "backend" / "whymath_backend"
_PROVENANCE = _REPO_ROOT / "data" / "corpus" / "concept_graph_v1" / "_provenance.json"

# 구 437 *데이터* reader 심볼(격하 대상) — 함수·클래스·ORM·모듈/테이블명.
# `_build_sync_engine`은 *제외*한다(공유 인프라 유틸·개념 데이터 read 아님·docstring 참조).
_READER_IDENTIFIERS = frozenset(
    {
        "fetch_node_meta",
        "ConceptNodeMeta",
        "ConceptEmbeddingIndex",
        "search_concepts",
        "ConceptNode",
        "ConceptEmbedding",
    }
)

# concept_graph 패키지 import 경로(런타임 계층에서 import 자체 금지 — 인프라 유틸 포함).
_CONCEPT_GRAPH_MODULE = "whymath_backend.l1.concept_graph"

# 런타임 계층(구 437 reader 0이어야 하는 스코프).
_RUNTIME_SUBPACKAGES = ("api", "l2", "l3", "l4")

# 구 437 코퍼스 디렉토리 토큰(빌드타임 소비처 식별용·문자열 리터럴로만 등장).
_LEGACY_CORPUS_TOKEN = "concept_graph_v1"

# audit/빌드타임 화이트리스트 — 구 437을 읽어도 되는 소비처(패키지 루트 상대·posix).
# 디렉토리 접두 또는 정확 파일 경로. 목록 밖 모듈이 구 437을 읽으면 (ii) red.
_AUDIT_WHITELIST = frozenset(
    {
        "l1/concept_atom_crosswalk",  # 크로스워크(derive·transfer) — provenance·이전 근거
        "l1/curriculum/populate.py",  # KR 교육과정 셀 빌드타임 적재 CLI
        # S2-03 원자 재연결 — 문제 태깅 src 태그를 크로스워크로 해석할 때 다리(graph.json의
        # concept_id→src_id)만 빌드타임에 읽는다(개념 *데이터* read 아님·런타임 reader 아님).
        "l1/problem_bank/populate.py",
        # P3-10 AI 품질 평가(audit 전용·런타임 아님) — 튜터 출력이 참조한 개념 code(= 437 canonical
        # id · P3-01 명세·P3-09 진단과 같은 공간)의 실재·이름·선수 관계를 대조하려고 ids·concepts·
        # prerequisite_edges 를 읽는다. 서빙 경로(api·l2·l3·l4)에서 import되지 않는다.
        "harness/ai_quality_registry.py",
    }
)

# (ii) 소비처 스캔에서 제외 — 격하 스냅샷 *본체*(reader 정의처)이지 외부 소비처가 아니다.
_LEGACY_HOME_PREFIXES = (
    "l1/concept_graph/",  # 격하된 legacy_snapshot 모듈 자신(reader 정의)
    "db/models/",  # ORM 정의(ConceptNode·ConceptEmbedding 테이블 매핑)
)


def _iter_py(root: Path) -> list[Path]:
    """root 하위 .py 파일(정렬)."""
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _reader_data_references(tree: ast.Module) -> set[str]:
    """AST에서 구 437 *data-reader 심볼*의 실제 참조를 수집(주석·docstring·문자열 제외).

    - import-name: `from ... import ConceptNode`(출처 무관 — db.models 경유도 포함)
    - 식별자: Name.id·Attribute.attr가 reader 심볼과 정확히 일치
    *모듈 import 자체*(`from ...concept_graph.embedding import _build_sync_engine`)는 여기서
    잡지 않는다 — `_build_sync_engine`은 공유 인프라 유틸이라 심볼명이 화이트리스트되지 않는다.
    docstring/문자열/주석은 Constant/토큰이라 여기 잡히지 않는다(오탐 차단).
    """
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _READER_IDENTIFIERS:
                    hits.add(f"import-name:{alias.name}")
        elif isinstance(node, ast.Name) and node.id in _READER_IDENTIFIERS:
            hits.add(f"name:{node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _READER_IDENTIFIERS:
            hits.add(f"attr:{node.attr}")
    return hits


def _concept_graph_package_imports(tree: ast.Module) -> set[str]:
    """concept_graph 패키지 import 문(심볼 무관·`_build_sync_engine` 인프라 포함)을 수집.

    런타임 계층((i))은 격하 패키지를 *어떤 심볼이든* import하면 안 된다(인프라 유틸도 격하 패키지
    거주 → 런타임 결합 금지). 이 엄격 검사는 (i) 전용이며 (ii) 화이트리스트에는 쓰지 않는다.
    """
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == _CONCEPT_GRAPH_MODULE or module.startswith(_CONCEPT_GRAPH_MODULE + "."):
                hits.add(f"import:{module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == _CONCEPT_GRAPH_MODULE or name.startswith(_CONCEPT_GRAPH_MODULE + "."):
                    hits.add(f"import:{name}")
    return hits


def _reads_legacy_corpus(tree: ast.Module) -> bool:
    """AST 문자열 리터럴에 구 437 코퍼스 토큰이 있으면 True(경로 상수·주석 제외)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _LEGACY_CORPUS_TOKEN in node.value:
                return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# (i) 런타임 437 reader = 0 — api·l2·l3·l4 AST 스캔
# ──────────────────────────────────────────────────────────────────────────
def test_runtime_layers_have_zero_legacy_437_readers() -> None:
    """런타임 계층(api·l2·l3·l4)에 구 437 data-reader의 실제 import/참조가 0건이어야 한다.

    신규 reader(예: `from whymath_backend.l1.concept_graph.retrieval import search_concepts`,
    `ConceptNode` ORM 질의)가 유입되면 red — 원자 백본이 runtime truth source라는 격하 전제 위반.
    """
    violations: dict[str, set[str]] = {}
    for sub in _RUNTIME_SUBPACKAGES:
        sub_root = _PKG_ROOT / sub
        assert sub_root.is_dir(), f"런타임 서브패키지 {sub} 부재 — 경로 확인"
        for path in _iter_py(sub_root):
            tree = _parse(path)
            hits = _reader_data_references(tree) | _concept_graph_package_imports(tree)
            if hits:
                violations[path.relative_to(_PKG_ROOT).as_posix()] = hits
    assert not violations, (
        "런타임 계층(api·l2·l3·l4)에서 구 437 legacy_snapshot reader가 발견됨 — "
        "원자 백본(search_atoms·fetch_atom_node_meta)을 쓰라. "
        f"위반: {dict(sorted((k, sorted(v)) for k, v in violations.items()))}"
    )


# ──────────────────────────────────────────────────────────────────────────
# (ii) audit/빌드타임 화이트리스트 — 구 437 소비처는 화이트리스트 안에만
# ──────────────────────────────────────────────────────────────────────────
def _is_whitelisted(relpath: str) -> bool:
    """패키지 루트 상대 경로가 화이트리스트(정확 파일 또는 디렉토리 접두)에 속하는가."""
    for entry in _AUDIT_WHITELIST:
        if relpath == entry or relpath.startswith(entry + "/"):
            return True
    return False


def test_legacy_437_consumers_are_within_audit_whitelist() -> None:
    """구 437(코퍼스/심볼)을 읽는 모듈은 audit/빌드타임 화이트리스트 안에만 존재한다.

    격하 스냅샷 본체(`l1/concept_graph/`·`db/models/`)는 소비처가 아니라 정의처라 스캔 제외.
    목록 밖 모듈이 구 437을 읽으면 red — 격하 우회(런타임 재유입) 차단.
    """
    consumers: dict[str, list[str]] = {}
    for path in _iter_py(_PKG_ROOT):
        relpath = path.relative_to(_PKG_ROOT).as_posix()
        if any(relpath.startswith(prefix) for prefix in _LEGACY_HOME_PREFIXES):
            continue
        tree = _parse(path)
        reasons: list[str] = sorted(_reader_data_references(tree))
        if _reads_legacy_corpus(tree):
            reasons.append("corpus:concept_graph_v1")
        if reasons:
            consumers[relpath] = reasons

    # sanity: 스캐너가 실제로 소비처를 찾는다(빈 결과 = 스캔 버그로 인한 무력화 방지).
    assert consumers, (
        "구 437 소비처가 하나도 발견되지 않음 — 스캐너가 무력화됐거나 코퍼스 소비가 모두 "
        "사라졌는지 확인하라(크로스워크·curriculum populate는 코퍼스를 읽어야 정상)."
    )

    outside = {rel: why for rel, why in consumers.items() if not _is_whitelisted(rel)}
    assert not outside, (
        "audit 화이트리스트 밖 모듈이 구 437 legacy_snapshot을 읽음 — 화이트리스트="
        f"{sorted(_AUDIT_WHITELIST)}. 위반: {dict(sorted(outside.items()))}. "
        "정당한 빌드타임 소비면 이 화이트리스트를 *의식적으로* 확장하라(런타임 재유입이면 금지)."
    )


# ──────────────────────────────────────────────────────────────────────────
# (iii) lifecycle 마커 존재 — _provenance.json 격하 표식
# ──────────────────────────────────────────────────────────────────────────
def test_provenance_lifecycle_marker_frozen() -> None:
    """코퍼스 `_provenance.json`에 legacy_snapshot 격하 마커가 존재한다(표식 제거 시 red)."""
    assert _PROVENANCE.is_file(), f"provenance 부재: {_PROVENANCE}"
    payload = json.loads(_PROVENANCE.read_text(encoding="utf-8"))
    lifecycle = payload.get("lifecycle")
    assert isinstance(lifecycle, dict), "_provenance.json에 lifecycle 키가 있어야 한다(격하 표식)"
    assert (
        lifecycle.get("status") == "legacy_snapshot"
    ), "lifecycle.status가 'legacy_snapshot'이어야 한다 — 격하 표식이 지워졌다."
    assert (
        lifecycle.get("non_runtime") is True
    ), "lifecycle.non_runtime이 true여야 한다 — 런타임 미참조 표식이 지워졌다."
