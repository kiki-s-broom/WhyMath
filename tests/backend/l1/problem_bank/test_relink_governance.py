"""problem_concept 원자 재연결 *거버넌스* — 실 코퍼스 대조 dangling 0 동결 (S2-03·hermetic·PG 불요).

커밋된 실 코퍼스(4 문제코퍼스·크로스워크·구 437 다리·원자 그래프)로 재연결 해석 체인
(src 태그 → bridge → crosswalk primary → 원자 code)을 실행해 참조 무결성을 동결한다
(`test_crosswalk_transfer_governance.py` 패턴 미러 — 모든 소스가 repo 커밋 코퍼스라 hermetic·
DB/네트워크 0):

  ① 소스 코퍼스 실재 — 4 문제코퍼스 + 크로스워크 + 다리(+ 원자 그래프) 부재 시 loud 실패
  ② 4 문제코퍼스 전 태그 해석 가능(dangling 0) — 알려진 예외는 빈 frozenset으로 동결
  ③ 해석 결과(primary_atom_code) ⊆ 원자 그래프 세부개념 code 집합
  ④ legacy 키공간 무교차 — primary code는 canonical(`math.` prefix)·src 공간과 겹치지 않는다
  ⑤ 코퍼스별 태그 수 하한 동결(v1≥6·generated_v0≥620·rephrased_v0≥429 — S3-12 위생 축소 반영,
     483→446(1차 37건)→443(지수 서술구 3건)→429(rotation-1 신규 3축+어형 붕괴 수기감사 14건)
     순차 탈락) — 스캐너 무력화 방지
  ⑥ 동일 문제·동일 role의 primary 접힘 0 동결 — 현 코퍼스는 접힘 무손실(재저작 시 여기서 감지)

코퍼스가 재유도·재저작되어 수치가 내려가거나 dangling이 생기면 여기서 잡는다(드리프트 감지).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    load_concept_src_bridge,
    load_crosswalk_records,
)
from whymath_backend.l1.problem_bank.populate import derive_src_to_primary_atom

# 레포 루트 앵커(tests/backend/l1/problem_bank/ → parents[4]) — CWD 상대 경로는
# CI(cwd=src/backend)에서 깨진다(crosswalk 거버넌스 `_ROOT` 선례).
_ROOT = Path(__file__).resolve().parents[4]
_CROSSWALK = _ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
_CONCEPT_GRAPH = _ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_ATOM_GRAPH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_FACTS = json.loads((_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))
# 4 문제코퍼스 — {이름: (경로, 태그 수 하한)} (⑤ 하한은 2026-07-09 실측 동결, mc_v0은 2026-07-29
# S3-12 rotation-1 concept_src_id 재고정 후 신규 편입). v0 3종의 하한은 그 코퍼스의 문제 수
# (문제당 태그 1개 — 실측 동일)를 사실 파일에서 읽는다: 문제 은퇴로 건수가 줄면 `sync`의
# corpus_facts.json diff가 의식적 리뷰 지점이 된다(손 하한 갱신 이력은 아래 주석에 보존).
_PROBLEM_CORPORA: dict[str, tuple[Path, int]] = {
    "problem_bank_v1": (_ROOT / "data" / "corpus" / "problem_bank_v1" / "problems.jsonl", 6),
    "problem_bank_generated_v0": (
        # QUAL-02 실중복 은퇴(2026-08-11)로 620→619 — 데모풀 동시노출 쌍의 스켈레톤 측
        # 1건(wm-skel-92cd1ba2bbf5) 제거. 판정 정본 docs/data/problem_duplicate_disposition_2026-08.md.
        _ROOT / "data" / "corpus" / "problem_bank_generated_v0" / "problems.jsonl",
        _FACTS["problem_bank.generated_v0"],
    ),
    "problem_bank_rephrased_v0": (
        # S3-12 발문 위생 일괄 적용(rephrased_corpus_hygiene)으로 483→446→443→429 정직 축소 —
        # 1차 37건(한자·가나 주입/메타 라벨/비표준 용어/방법-값 부정합/조사 오류) +
        # 지수 서술구 허상 삽입 3건(⑥축 신설) +
        # rotation-1 재검수 발견 신규 3축(괄호 메타 누출·차원 오기술·개념 오치환) 12건 +
        # 어형 붕괴 수기감사 확정 2건(`_KNOWN_DEFECTIVE_SLUGS`) = 14건 추가 탈락.
        # QUAL-02 실중복 은퇴(2026-08-11)로 429→421 — 무변화 재서술 사본 8건(위생 위반이
        # 아니라 중복 은퇴). 판정 정본 동상.
        _ROOT / "data" / "corpus" / "problem_bank_rephrased_v0" / "problems.jsonl",
        _FACTS["problem_bank.rephrased_v0"],
    ),
    "problem_bank_misconception_mc_v0": (
        # S3-12 rotation-1이 45밴드 중 13개의 concept_src_id(`_TEMPLATE_META`)가 재태깅된
        # standard_codes와 무관한 구 개념을 계속 가리키던 결함(M0052 크로스링크 회귀와 동일
        # 계통 — 표시용 태그만 고치고 그래프 앵커를 놓침)을 발견·전수 교정 후 신규 편입.
        # 편입 전에는 이 코퍼스가 거버넌스 밖이라 저 13건 dangling-등가 결함이 무기한 미검출
        # 상태였다(재발 방지 — 이 테스트가 이제 4번째 코퍼스로 상시 감시).
        _ROOT / "data" / "corpus" / "problem_bank_misconception_mc_v0" / "problems.jsonl",
        _FACTS["problem_bank.misconception_mc_v0"],
    ),
}

# ② 해석 예외 동결 — 현재 미해석 허용 태그는 *없다*. 여기 항목을 추가하려면 데이터카드 근거가
# 필요하다(조용한 확장 금지 — dangling을 예외로 눙치지 말 것).
_ALLOWED_DANGLING: frozenset[str] = frozenset()


def _iter_problem_rows(path: Path) -> list[dict[str, object]]:
    """문제코퍼스 JSONL 원시 파싱 — 태그 축만 보므로 Problem 검증은 생략(hermetic·빠름)."""
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _corpus_tags(path: Path) -> list[tuple[str, str, str]]:
    """(slug, concept_src_id, role) 태그 인스턴스 목록."""
    out: list[tuple[str, str, str]] = []
    for row in _iter_problem_rows(path):
        slug = str(row.get("slug"))
        for tag in row.get("concepts") or []:
            if isinstance(tag, dict):
                out.append((slug, str(tag.get("concept_src_id")), str(tag.get("role"))))
    return out


def _src_to_primary() -> dict[str, str]:
    return derive_src_to_primary_atom(
        load_crosswalk_records(_CROSSWALK), load_concept_src_bridge(_CONCEPT_GRAPH)
    )


def _atom_leaf_universe() -> set[str]:
    payload = json.loads(_ATOM_GRAPH.read_text(encoding="utf-8"))
    return {str(c["code"]) for c in payload["concepts"] if c.get("level") == "세부개념"}


# ── ① 소스 코퍼스 실재 (loud) ───────────────────────────────────────────────
def test_corpora_exist() -> None:
    """소스 코퍼스 전부 커밋 존재 — 부재 시 조용한 skip 대신 명시 실패(거버넌스는 loud)."""
    paths = [_CROSSWALK, _CONCEPT_GRAPH, _ATOM_GRAPH] + [p for p, _ in _PROBLEM_CORPORA.values()]
    for path in paths:
        assert path.exists(), f"코퍼스 부재: {path}"


# ── ② 3 문제코퍼스 전 태그 dangling 0 ──────────────────────────────────────
def test_all_problem_tags_resolve_to_primary_atom() -> None:
    """3 문제코퍼스의 모든 `concept_src_id` 태그가 크로스워크 해석 맵에 닿는다(dangling 0)."""
    src_to_primary = _src_to_primary()
    for name, (path, _) in _PROBLEM_CORPORA.items():
        tags = {src for _, src, _ in _corpus_tags(path)}
        dangling = tags - set(src_to_primary) - _ALLOWED_DANGLING
        assert dangling == set(), (
            f"{name}: 크로스워크로 해석 불가한 태그(dangling): {sorted(dangling)} — "
            f"재연결 후 이 태그의 problem_concept은 orphan skip으로 소실된다."
        )


# ── ③ 해석 결과 ⊆ 원자 그래프 세부개념 ─────────────────────────────────────
def test_resolved_primaries_are_atom_graph_leaves() -> None:
    """태그 해석 결과(primary_atom_code)는 전부 atom_graph_v1의 세부개념 code다."""
    src_to_primary = _src_to_primary()
    leaves = _atom_leaf_universe()
    used = {
        src_to_primary[src]
        for _, (path, _) in _PROBLEM_CORPORA.items()
        for _, src, _ in _corpus_tags(path)
        if src in src_to_primary
    }
    dangling = used - leaves
    assert dangling == set(), f"원자 그래프 세부개념에 없는 primary(dangling): {sorted(dangling)}"


# ── ④ legacy 키공간 무교차 ─────────────────────────────────────────────────
def test_primary_codes_disjoint_from_legacy_keyspaces() -> None:
    """primary code는 구 437 canonical(`math.` prefix)·src 키공간과 겹치지 않는다(축 분리)."""
    bridge = load_concept_src_bridge(_CONCEPT_GRAPH)  # canonical concept_id → src_id
    src_to_primary = _src_to_primary()
    primaries = set(src_to_primary.values())
    # canonical 공간(`math.` prefix) 무교차 + prefix 자체 부재(이중 확인).
    assert primaries & set(bridge) == set()
    assert not any(p.startswith("math.") for p in primaries)
    # src 공간(HK06·H:12… 등) 무교차 — 재연결이 legacy 키로 회귀하면 여기서 red.
    assert primaries & set(bridge.values()) == set()


# ── ⑤ 코퍼스별 태그 수 하한 동결 ────────────────────────────────────────────
def test_tag_count_lower_bounds() -> None:
    """코퍼스별 태그 인스턴스 수 하한(실측 동결) — 스캐너 무력화·코퍼스 축소 드리프트 감지."""
    for name, (path, lower) in _PROBLEM_CORPORA.items():
        count = len(_corpus_tags(path))
        assert count >= lower, f"{name}: 태그 수 {count} < 하한 {lower}(코퍼스 축소 드리프트?)"


# ── ⑥ 동일 문제·동일 role primary 접힘 0 동결 ──────────────────────────────
def test_no_primary_collapse_within_problem_role() -> None:
    """현 코퍼스는 한 문제 안에서 같은 role의 두 태그가 같은 primary로 접히지 않는다(무손실).

    접힘이 생기면 relevance max 규칙이 발동하며 태깅 행 수가 태그 수보다 줄어든다 — 그 자체는
    정상 동작이나, *현재* 코퍼스가 무손실임을 동결해 재저작 시 의도치 않은 접힘을 감지한다.
    """
    src_to_primary = _src_to_primary()
    for name, (path, _) in _PROBLEM_CORPORA.items():
        counter: Counter[tuple[str, str, str]] = Counter(
            (slug, src_to_primary[src], role)
            for slug, src, role in _corpus_tags(path)
            if src in src_to_primary
        )
        collapsed = {key: n for key, n in counter.items() if n > 1}
        assert collapsed == {}, f"{name}: (문제, primary, role) 접힘 발생: {collapsed}"
