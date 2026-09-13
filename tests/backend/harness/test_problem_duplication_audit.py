"""문항 코퍼스 중복 감사 CLI 테스트 — T1/T2 판정 변별력·결정론·정직 회계 동결(hermetic).

대상: `whymath_backend.harness.problem_duplication_audit`(QUAL-01 관측 리포트). 실 DB·LLM·네트워크
0 — 순수 로직 테스트는 `CorpusLoad`/`DuplicationRecord`를 직접 조립하고(파일 I/O 없이 `build_report`
호출 가능함을 그대로 증명), 로더·CLI 테스트만 `tmp_path`에 소형 JSONL 픽스처를 만든다.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): 각 테스트는 *그 규약이 깨진 구현에서 실제로
실패하는지*를 기준으로 짰다 —
  - 계보(`relations`) 배제를 빼먹으면 정당한 형제가 "실중복"으로 잘못 잡혀 실패한다.
  - 계보 배제를 과하게(예: 같은 코퍼스 전체를 한 요소로) 하면 진짜 중복을 못 잡아 실패한다.
  - 조건 (a)(서로 다른 코퍼스)를 빼먹으면 같은 코퍼스 내부 중복도 "실중복"으로 잡혀 실패한다.
  - "데이터없음"과 "비어있음"을 합치면 상태 단언이 실패한다.
  - 실중복 발견 시 exit 1을 내면 게이트가 아니라는 동결이 깨진다.
  - dict/튜플 삽입 순서에 의존해 렌더하면 역순 입력 동일성 테스트가 실패한다.

마지막 절(§실제 코퍼스 스냅샷)은 유일하게 실 코퍼스(`data/corpus/`)를 읽는 통합 테스트다 —
QUAL-01 실측(T1 해소·T2 신규 발견)에서 시작해 QUAL-02 은퇴·PB-13 회수(71쌍 재발)·QUAL-07 처분
(0쌍)까지의 현행 수치를 회귀 고정한다. 두 코퍼스의 파라미터 공간 서로소 분리 자체는
`tests/backend/l3/equivalent/test_quotient_rule_space_disjointness.py`가 따로 동결한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import problem_duplication_audit as pda

# ──────────────────────────────────────────────────────────────────────────
# 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────────────────


def _rec(
    corpus: str,
    slug: str | None,
    text: str | None,
    *,
    line_no: int = 1,
    question_format: str | None = "단답형",
    identity_id: str | None = None,
    relations: tuple[pda.RelationTag, ...] = (),
) -> pda.DuplicationRecord:
    """`DuplicationRecord`를 직접 조립 — 파일 I/O 없이 순수 로직만 검증할 때 쓴다."""
    return pda.DuplicationRecord(
        corpus=corpus,
        line_no=line_no,
        problem_id=None,
        slug=slug,
        question_text=text,
        question_format=question_format,
        identity_id=identity_id,
        relations=relations,
    )


def _load(name: str, records: tuple[pda.DuplicationRecord, ...]) -> pda.CorpusLoad:
    """`CorpusLoad`를 직접 조립 — `path`는 존재하지 않아도 된다(`build_report`는 안 읽는다)."""
    return pda.CorpusLoad(
        name=name,
        path=Path(f"/nonexistent/{name}"),
        status="적재됨" if records else "비어있음",
        records=records,
        parse_errors=(),
    )


def _problem_json(
    *,
    slug: str,
    question_text: str = "기본 발문입니다.",
    question_format: str | None = "단답형",
    problem_id: str | None = None,
    identity_id: str | None = None,
    relations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"slug": slug, "question_text": question_text}
    if question_format is not None:
        payload["question_format"] = question_format
    if problem_id is not None:
        payload["problem_id"] = problem_id
    if identity_id is not None:
        payload["identity_id"] = identity_id
    if relations is not None:
        payload["relations"] = relations
    return payload


def _write_corpus(root: Path, name: str, problems: list[dict[str, object]]) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / pda.CORPUS_FILE_NAME
    path.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in problems), encoding="utf-8"
    )
    return path


# ──────────────────────────────────────────────────────────────────────────
# normalize_question_text — T2 조건 (b)
# ──────────────────────────────────────────────────────────────────────────
def test_normalize_collapses_whitespace_and_applies_nfc() -> None:
    a = pda.normalize_question_text("이차방정식   x^2-5x+6=0\n의 두 근은?")
    b = pda.normalize_question_text("이차방정식 x^2-5x+6=0 의 두 근은?")
    assert a == b


def test_normalize_none_and_blank_both_become_none() -> None:
    assert pda.normalize_question_text(None) is None
    assert pda.normalize_question_text("   ") is None
    assert pda.normalize_question_text("") is None


def test_normalize_does_not_touch_punctuation_or_digits() -> None:
    """의미 정규화는 하지 않는다 — 표면 텍스트만 비교(오탐 축소, 모듈 docstring)."""
    assert pda.normalize_question_text("근을 구하시오.") != pda.normalize_question_text(
        "근을 구해라."
    )
    assert pda.normalize_question_text("x^2") != pda.normalize_question_text("x²")


# ──────────────────────────────────────────────────────────────────────────
# 로더 — 상태 구분·파싱 실패·relations 파싱
# ──────────────────────────────────────────────────────────────────────────
def test_missing_file_and_empty_file_are_different_states(tmp_path: Path) -> None:
    empty = _write_corpus(tmp_path, "problem_bank_empty", [])
    missing = tmp_path / "problem_bank_ghost" / pda.CORPUS_FILE_NAME

    empty_load = pda.load_corpus_file(empty, name="problem_bank_empty")
    missing_load = pda.load_corpus_file(missing, name="problem_bank_ghost")

    assert empty_load.status == "비어있음"
    assert missing_load.status == "데이터없음"
    assert len(empty_load.records) == len(missing_load.records) == 0


def test_parse_failures_are_counted_with_exception_type(tmp_path: Path) -> None:
    """파싱 실패 라인을 조용히 버리지 않고 예외 타입명과 함께 보고한다(침묵 실패 금지)."""
    path = tmp_path / "problem_bank_broken" / pda.CORPUS_FILE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_problem_json(slug="ok"), ensure_ascii=False)
        + "\n"
        + "{ not json\n"  # JSONDecodeError
        + json.dumps([1, 2], ensure_ascii=False)  # TypeError(object 아님)
        + "\n"
        + json.dumps(
            {"slug": "no-parent", "relations": [{"relation_type": "유사"}]}
        )  # parent_slug 누락
        + "\n",
        encoding="utf-8",
    )
    load = pda.load_corpus_file(path, name="problem_bank_broken")

    assert len(load.records) == 1
    assert [e.line_no for e in load.parse_errors] == [2, 3, 4]
    assert [e.error_type for e in load.parse_errors] == [
        "JSONDecodeError",
        "TypeError",
        "TypeError",
    ]
    assert all(e.corpus == "problem_bank_broken" for e in load.parse_errors)


def test_load_parses_relations_and_identity_id(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_rel",
        [
            _problem_json(
                slug="child",
                identity_id="id-1",
                relations=[
                    {"parent_slug": "parent", "relation_type": "변형", "similarity_score": 1.0}
                ],
            )
        ],
    )
    load = pda.load_corpus_file(corpus, name="problem_bank_rel")
    assert len(load.records) == 1
    rec = load.records[0]
    assert rec.identity_id == "id-1"
    assert rec.relations == (pda.RelationTag(parent_slug="parent", relation_type="변형"),)


# ──────────────────────────────────────────────────────────────────────────
# T1 — 슬러그 충돌
# ──────────────────────────────────────────────────────────────────────────
def test_find_slug_collisions_detects_cross_corpus_overlap() -> None:
    loads = (
        _load(
            "problem_bank_a",
            (_rec("problem_bank_a", "shared-1", "t1"), _rec("problem_bank_a", "shared-2", "t2")),
        ),
        _load(
            "problem_bank_b",
            (_rec("problem_bank_b", "shared-1", "t3"), _rec("problem_bank_b", "unique", "t4")),
        ),
        _load("problem_bank_c", (_rec("problem_bank_c", "shared-2", "t5"),)),
    )
    collisions, pair_counts = pda.find_slug_collisions(loads)

    assert len(collisions) == 2
    assert {(c.corpus_a, c.corpus_b, c.slug) for c in collisions} == {
        ("problem_bank_a", "problem_bank_b", "shared-1"),
        ("problem_bank_a", "problem_bank_c", "shared-2"),
    }
    # 스캔한 전 C(3,2)=3쌍이 사전에 전부 등장한다(0건 쌍도 정직 회계로 포함).
    assert pair_counts == {
        ("problem_bank_a", "problem_bank_b"): 1,
        ("problem_bank_a", "problem_bank_c"): 1,
        ("problem_bank_b", "problem_bank_c"): 0,
    }


def test_find_slug_collisions_zero_when_no_overlap() -> None:
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "a1", "t1"),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "b1", "t2"),)),
    )
    collisions, pair_counts = pda.find_slug_collisions(loads)
    assert collisions == ()
    assert pair_counts == {("problem_bank_a", "problem_bank_b"): 0}


def test_find_slug_collisions_pair_key_order_independent_of_input_order() -> None:
    """입력 `loads` 순서(역순)와 무관하게 같은 (정렬된) 쌍 키를 낸다 — 결정론."""
    a = _load("problem_bank_a", (_rec("problem_bank_a", "s", "t"),))
    b = _load("problem_bank_b", (_rec("problem_bank_b", "s", "t"),))
    _, forward = pda.find_slug_collisions((a, b))
    _, backward = pda.find_slug_collisions((b, a))
    assert forward == backward == {("problem_bank_a", "problem_bank_b"): 1}


# ──────────────────────────────────────────────────────────────────────────
# 계보 그래프 — T2 조건 (c)
# ──────────────────────────────────────────────────────────────────────────
def test_lineage_graph_direct_edge_is_legitimate_sibling() -> None:
    loads = (
        _load(
            "problem_bank_x",
            (
                _rec(
                    "problem_bank_x", "child", "t", relations=(pda.RelationTag("parent", "변형"),)
                ),
                _rec("problem_bank_x", "parent", "t2"),
            ),
        ),
    )
    adjacency = pda.build_lineage_graph(loads)
    assert pda.is_legitimate_sibling("child", "parent", adjacency) is True
    assert pda.is_legitimate_sibling("parent", "child", adjacency) is True  # 무향


def test_lineage_graph_transitive_closure_via_shared_parent() -> None:
    """A→parent=B, C→parent=B 이면 A·C는 직접 연결이 없어도 같은 연결요소(형제의 형제)."""
    loads = (
        _load(
            "problem_bank_x",
            (
                _rec("problem_bank_x", "A", "tA", relations=(pda.RelationTag("B", "유사"),)),
                _rec("problem_bank_x", "B", "tB"),
                _rec("problem_bank_x", "C", "tC", relations=(pda.RelationTag("B", "유사"),)),
            ),
        ),
    )
    adjacency = pda.build_lineage_graph(loads)
    assert pda.is_legitimate_sibling("A", "C", adjacency) is True


def test_lineage_graph_unrelated_slugs_are_not_siblings() -> None:
    loads = (
        _load(
            "problem_bank_x",
            (
                _rec("problem_bank_x", "A", "tA", relations=(pda.RelationTag("B", "유사"),)),
                _rec("problem_bank_x", "B", "tB"),
                _rec("problem_bank_x", "Z", "tZ"),  # 그래프에 아예 없음
            ),
        ),
    )
    adjacency = pda.build_lineage_graph(loads)
    assert pda.is_legitimate_sibling("A", "Z", adjacency) is False
    assert pda.is_legitimate_sibling("Z", "Z2-not-a-node", adjacency) is False


def test_lineage_graph_ignores_relation_type_value() -> None:
    """관계 유형(변형/유사/선수/심화/대조) 무관하게 전부 배제 신호로 쓴다(모듈 docstring)."""
    for rel_type in ("변형", "유사", "선수", "심화", "대조", "심지어-스키마밖값"):
        loads = (
            _load(
                "problem_bank_x",
                (
                    _rec(
                        "problem_bank_x",
                        "child",
                        "t",
                        relations=(pda.RelationTag("parent", rel_type),),
                    ),
                    _rec("problem_bank_x", "parent", "t2"),
                ),
            ),
        )
        adjacency = pda.build_lineage_graph(loads)
        assert pda.is_legitimate_sibling("child", "parent", adjacency) is True, rel_type


# ──────────────────────────────────────────────────────────────────────────
# T2 — 실중복 판정 변별력(핵심 테스트)
# ──────────────────────────────────────────────────────────────────────────
def test_find_duplicate_pairs_distinguishes_siblings_from_real_duplicates() -> None:
    """형제(계보 선언)는 안 잡고, 계보 없는 진짜 중복은 잡는다 — 양쪽을 한 픽스처로 실측(변별력).

    - alpha/wm-skel-parent ↔ beta/wm-skel-parent-rephrased: 텍스트 동일 + `변형` 관계 선언
      → 정당한 형제, 실중복 아님.
    - alpha/wm-real-dup-a ↔ beta/wm-real-dup-b: 텍스트 동일 + 계보 선언 전혀 없음
      → 실중복 확정.
    """
    shared_text = "삼차함수 f(x) = x^3 - 3x 의 극댓값을 구하시오."
    dup_text = "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오."
    alpha = _load(
        "problem_bank_alpha",
        (
            _rec("problem_bank_alpha", "wm-skel-parent", shared_text),
            _rec("problem_bank_alpha", "wm-real-dup-a", dup_text),
        ),
    )
    beta = _load(
        "problem_bank_beta",
        (
            _rec(
                "problem_bank_beta",
                "wm-skel-parent-rephrased",
                shared_text,
                relations=(pda.RelationTag("wm-skel-parent", "변형"),),
            ),
            _rec("problem_bank_beta", "wm-real-dup-b", dup_text),
        ),
    )
    pairs = pda.find_duplicate_pairs((alpha, beta), demo_pool=frozenset())

    slugs_involved = {(p.slug_a, p.slug_b) for p in pairs}
    assert ("wm-skel-parent", "wm-skel-parent-rephrased") not in slugs_involved  # 형제 — 배제됨
    assert len(pairs) == 1
    assert pairs[0].slug_a == "wm-real-dup-a"
    assert pairs[0].slug_b == "wm-real-dup-b"
    assert pairs[0].normalized_text == dup_text


def test_find_duplicate_pairs_ignores_same_corpus_matches() -> None:
    """조건 (a) — 같은 코퍼스 내부의 텍스트 일치는 실중복으로 잡지 않는다."""
    loads = (
        _load(
            "problem_bank_alpha",
            (
                _rec("problem_bank_alpha", "s1", "같은 텍스트", question_format="단답형"),
                _rec("problem_bank_alpha", "s2", "같은 텍스트", question_format="객관식"),
            ),
        ),
    )
    pairs = pda.find_duplicate_pairs(loads, demo_pool=frozenset())
    assert pairs == ()


def test_find_duplicate_pairs_matches_after_whitespace_normalization() -> None:
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", "이차방정식   x^2=4  의 해는?"),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", "이차방정식 x^2=4 의 해는?"),)),
    )
    pairs = pda.find_duplicate_pairs(loads, demo_pool=frozenset())
    assert len(pairs) == 1


def test_find_duplicate_pairs_records_same_question_format_flag() -> None:
    text = "같은 발문"
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", text, question_format="단답형"),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", text, question_format="객관식"),)),
    )
    pairs = pda.find_duplicate_pairs(loads, demo_pool=frozenset())
    assert len(pairs) == 1
    assert pairs[0].same_question_format is False
    assert pairs[0].question_format_a == "단답형"
    assert pairs[0].question_format_b == "객관식"


def test_find_duplicate_pairs_demo_pool_co_exposed_requires_both_sides() -> None:
    text = "같은 발문"
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", text),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", text),)),
    )
    only_a = pda.find_duplicate_pairs(loads, demo_pool=frozenset({"problem_bank_a"}))
    both = pda.find_duplicate_pairs(
        loads, demo_pool=frozenset({"problem_bank_a", "problem_bank_b"})
    )
    assert only_a[0].demo_pool_co_exposed is False
    assert both[0].demo_pool_co_exposed is True


def test_find_duplicate_pairs_records_without_slug_or_text_are_excluded() -> None:
    loads = (
        _load(
            "problem_bank_a",
            (
                _rec("problem_bank_a", None, "텍스트인데 슬러그 없음"),
                _rec("problem_bank_a", "s1", None),
            ),
        ),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", "텍스트인데 슬러그 없음"),)),
    )
    pairs = pda.find_duplicate_pairs(loads, demo_pool=frozenset())
    assert pairs == ()  # slug 없는 쪽은 애초에 그룹핑 대상이 아니다


def test_count_cross_corpus_text_matches_excludes_same_corpus() -> None:
    loads = (
        _load(
            "problem_bank_a",
            (
                _rec("problem_bank_a", "s1", "T", question_format="단답형"),
                _rec("problem_bank_a", "s2", "T", question_format="객관식"),
            ),
        ),
        _load("problem_bank_b", (_rec("problem_bank_b", "s3", "T"),)),
    )
    # a 내부 (s1,s2)는 안 세고, (s1,s3)·(s2,s3) cross-corpus 2건만 센다.
    assert pda.count_cross_corpus_text_matches(loads) == 2


def test_count_same_corpus_text_duplicates_counts_groups_not_records() -> None:
    loads = (
        _load(
            "problem_bank_a",
            (
                _rec("problem_bank_a", "s1", "T1", question_format="단답형"),
                _rec("problem_bank_a", "s2", "T1", question_format="객관식"),
                _rec("problem_bank_a", "s3", "T2", question_format="단답형"),
                _rec("problem_bank_a", "s4", "T2", question_format="객관식"),
            ),
        ),
    )
    assert pda.count_same_corpus_text_duplicates(loads) == {"problem_bank_a": 2}


# ──────────────────────────────────────────────────────────────────────────
# build_report — 순수성·결정론
# ──────────────────────────────────────────────────────────────────────────
def test_build_report_is_pure_and_callable_without_file_io() -> None:
    """`build_report`는 이미 메모리에 있는 `CorpusLoad`만으로 계산한다 — path는 존재하지 않아도 된다."""
    text = "같은 발문"
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", text),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", text),)),
    )
    report = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    assert report.duplicate_pair_count == 1
    assert report.total_problems == 2
    assert report.corpus_pairs_scanned == 1


def test_build_report_honest_accounting_counts_gaps() -> None:
    loads = (
        _load(
            "problem_bank_a",
            (
                _rec("problem_bank_a", None, "텍스트"),  # slug 없음
                _rec("problem_bank_a", "s1", None),  # 텍스트 없음
                _rec("problem_bank_a", "s2", "   "),  # 공백만(텍스트 없음과 동치)
            ),
        ),
    )
    report = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    assert report.records_without_slug == 1
    assert report.records_without_question_text == 2


def test_build_report_internal_duplicate_slug_total() -> None:
    """코퍼스 내부에서 slug가 반복되면(데이터 정합성 위반) 정직 회계로 센다."""
    loads = (
        _load(
            "problem_bank_a",
            (
                _rec("problem_bank_a", "dup", "t1", line_no=1),
                _rec("problem_bank_a", "dup", "t2", line_no=2),
                _rec("problem_bank_a", "unique", "t3", line_no=3),
            ),
        ),
    )
    report = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    assert report.internal_duplicate_slug_total == 1  # 3레코드 - 2고유슬러그


def test_build_report_lineage_excluded_count_matches_raw_minus_confirmed() -> None:
    shared_text = "형제 텍스트"
    dup_text = "진짜 중복 텍스트"
    alpha = _load(
        "problem_bank_alpha",
        (
            _rec("problem_bank_alpha", "parent", shared_text),
            _rec("problem_bank_alpha", "dup-a", dup_text),
        ),
    )
    beta = _load(
        "problem_bank_beta",
        (
            _rec(
                "problem_bank_beta",
                "child",
                shared_text,
                relations=(pda.RelationTag("parent", "변형"),),
            ),
            _rec("problem_bank_beta", "dup-b", dup_text),
        ),
    )
    report = pda.build_report((alpha, beta), demo_pool=frozenset(), demo_pool_status="파일없음")
    assert report.cross_corpus_text_match_candidates == 2
    assert report.duplicate_pair_count == 1
    assert report.lineage_excluded_pair_count == 1


def test_build_report_output_independent_of_loads_insertion_order() -> None:
    text = "같은 발문"
    alpha = _load("problem_bank_alpha", (_rec("problem_bank_alpha", "s1", text),))
    beta = _load("problem_bank_beta", (_rec("problem_bank_beta", "s2", text),))

    forward = pda.build_report((alpha, beta), demo_pool=frozenset(), demo_pool_status="파일없음")
    backward = pda.build_report((beta, alpha), demo_pool=frozenset(), demo_pool_status="파일없음")

    assert pda.render_report(forward) == pda.render_report(backward)
    assert pda.dump_json(forward) == pda.dump_json(backward)


def test_render_and_json_are_byte_identical_across_runs() -> None:
    text = "같은 발문"
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", text),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", text),)),
    )
    r1 = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    r2 = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    assert pda.render_report(r1) == pda.render_report(r2)
    assert pda.dump_json(r1) == pda.dump_json(r2)


def test_render_report_announces_gate_free_status_even_with_duplicates() -> None:
    text = "같은 발문"
    loads = (
        _load("problem_bank_a", (_rec("problem_bank_a", "s1", text),)),
        _load("problem_bank_b", (_rec("problem_bank_b", "s2", text),)),
    )
    report = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    rendered = pda.render_report(report)
    assert "실중복 확정: 1쌍" in rendered
    assert "T3" in rendered  # 비-기준 문서화 절이 항상 포함된다


# ──────────────────────────────────────────────────────────────────────────
# 데모 풀 실재성 — scripts/demo/seed_demo.py 파싱
# ──────────────────────────────────────────────────────────────────────────
def test_demo_pool_corpora_extracts_from_seed_demo_source(tmp_path: Path) -> None:
    seed = tmp_path / "seed_demo.py"
    seed.write_text(
        "from pathlib import Path\n"
        '_CORPUS_ROOT = Path("/x")\n'
        "_CORPORA: tuple[Path, ...] = (\n"
        '    _CORPUS_ROOT / "problem_bank_v1" / "problems.jsonl",\n'
        '    _CORPUS_ROOT / "problem_bank_generated_v0" / "problems.jsonl",\n'
        ")\n",
        encoding="utf-8",
    )
    assert pda.demo_pool_corpora(seed) == frozenset(
        {"problem_bank_v1", "problem_bank_generated_v0"}
    )


def test_demo_pool_corpora_missing_file_returns_empty(tmp_path: Path) -> None:
    assert pda.demo_pool_corpora(tmp_path / "no-such-seed.py") == frozenset()


# ──────────────────────────────────────────────────────────────────────────
# QUAL-03 — 재서술 무변화 직접 측정(순수 로직·파일 I/O 없음)
# ──────────────────────────────────────────────────────────────────────────
class TestBuildGlobalSlugIndex:
    def test_first_wins_by_corpus_name_alphabetical(self) -> None:
        # 방어적 규칙 — 슬러그 충돌(T1)이 0건인 현재 코퍼스 상태에 의존하지 않는다는 확인.
        beta = _load("problem_bank_beta", (_rec("problem_bank_beta", "shared", "베타 텍스트"),))
        alpha = _load("problem_bank_alpha", (_rec("problem_bank_alpha", "shared", "알파 텍스트"),))
        index = pda.build_global_slug_index((beta, alpha))  # 입력 순서는 역순으로 준다
        corpus, record = index["shared"]
        assert corpus == "problem_bank_alpha"  # 코퍼스명 오름차순 first-wins
        assert record.question_text == "알파 텍스트"

    def test_missing_slug_absent_from_index(self) -> None:
        load = _load("problem_bank_a", (_rec("problem_bank_a", None, "슬러그 없는 문항"),))
        assert pda.build_global_slug_index((load,)) == {}


class TestMeasureRephraseNoopDefect:
    """직접 측정 4분류(무변화/정상변화/부모미선언/고아참조) — 정직 회계 각각 정확히 계상."""

    _PARENT_TEXT = "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오."

    def _corpora(
        self, rephrased_records: tuple[pda.DuplicationRecord, ...]
    ) -> tuple[pda.CorpusLoad, ...]:
        generated = _load(
            "problem_bank_generated_v0",
            (_rec("problem_bank_generated_v0", "parent-1", self._PARENT_TEXT),),
        )
        rephrased = _load("problem_bank_rephrased_v0", rephrased_records)
        return (generated, rephrased)

    def test_unchanged_when_normalized_text_matches_parent(self) -> None:
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-1",
            self._PARENT_TEXT,  # 원본과 완전 동일
            relations=(pda.RelationTag("parent-1", "변형"),),
        )
        report = pda.measure_rephrase_noop_defect(self._corpora((child,)))
        assert report.total == 1
        assert (report.unchanged_count, report.changed_count) == (1, 0)
        assert report.records[0].status == "무변화"
        assert report.records[0].parent_corpus == "problem_bank_generated_v0"

    def test_unchanged_via_whitespace_only_normalization(self) -> None:
        # 직접 측정도 정규화 비교를 쓴다(단순 `==`이 아님) — 공백만 다른 사례도 무변화로 잡는다.
        variant = "이차방정식  x^2 - 5x + 6 = 0 의  두 근 중 큰 근을 구하시오."
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-2",
            variant,
            relations=(pda.RelationTag("parent-1", "변형"),),
        )
        report = pda.measure_rephrase_noop_defect(self._corpora((child,)))
        assert report.records[0].status == "무변화"

    def test_changed_when_text_differs(self) -> None:
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-3",
            "완전히 다른 발문입니다.",
            relations=(pda.RelationTag("parent-1", "변형"),),
        )
        report = pda.measure_rephrase_noop_defect(self._corpora((child,)))
        assert (report.unchanged_count, report.changed_count) == (0, 1)
        assert report.records[0].status == "정상변화"

    def test_no_parent_declared_when_relations_empty(self) -> None:
        child = _rec("problem_bank_rephrased_v0", "child-4", "발문", relations=())
        report = pda.measure_rephrase_noop_defect(self._corpora((child,)))
        assert report.no_parent_declared_count == 1
        assert report.records[0].status == "부모미선언"
        assert report.records[0].parent_slug is None
        # 측정 불가 — 무변화/정상변화 분모에서 제외(조용히 넣거나 빼지 않는다, 정직 회계).
        assert report.measurable_count == 0

    def test_orphan_when_parent_slug_not_found_anywhere(self) -> None:
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-5",
            "발문",
            relations=(pda.RelationTag("ghost-slug-없음", "변형"),),
        )
        report = pda.measure_rephrase_noop_defect(self._corpora((child,)))
        assert report.orphan_parent_count == 1
        assert report.records[0].status == "고아참조"
        assert report.records[0].parent_slug == "ghost-slug-없음"
        assert report.measurable_count == 0

    def test_first_relation_used_when_multiple_declared(self) -> None:
        # 다중 관계 — relations[0]만 참조 부모로 쓴다(문서화된 결정, 실측 데이터는 항상 1개뿐).
        # 첫 번째는 텍스트가 다른(정상변화) 부모, 두 번째는 텍스트가 같은(무변화) 부모를 가리켜
        # 두 판정이 서로 달라지게 만들어 "첫 번째만 본다"는 규칙 자체를 고정한다.
        other_parent_same_text = _rec(
            "problem_bank_generated_v0", "parent-same-text", self._PARENT_TEXT
        )
        generated = _load(
            "problem_bank_generated_v0",
            (
                _rec("problem_bank_generated_v0", "parent-1", self._PARENT_TEXT),
                other_parent_same_text,
            ),
        )
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-multi",
            "완전히 다른 발문입니다.",  # parent-1과는 다름, parent-same-text와도 다름(자기 텍스트 자체가 다름)
            relations=(
                pda.RelationTag("parent-1", "변형"),
                pda.RelationTag("parent-same-text", "유사"),
            ),
        )
        rephrased = _load("problem_bank_rephrased_v0", (child,))
        report = pda.measure_rephrase_noop_defect((generated, rephrased))
        assert report.records[0].parent_slug == "parent-1"  # 두 번째 관계는 무시됨
        assert report.records[0].status == "정상변화"

    def test_target_corpus_absent_returns_empty_report(self) -> None:
        loads = (_load("problem_bank_other", (_rec("problem_bank_other", "s1", "텍스트"),)),)
        report = pda.measure_rephrase_noop_defect(loads)
        assert report.total == 0
        assert report.records == ()
        assert report.unchanged_rate is None
        assert report.measurable_count == 0

    def test_unchanged_rate_and_measurable_count(self) -> None:
        # 무변화 2 · 정상변화 1 · 부모미선언 1 · 고아참조 1 → 분모 3, 비율 2/3.
        records = (
            _rec(
                "problem_bank_rephrased_v0",
                "c-unchanged-1",
                self._PARENT_TEXT,
                relations=(pda.RelationTag("parent-1", "변형"),),
            ),
            _rec(
                "problem_bank_rephrased_v0",
                "c-unchanged-2",
                self._PARENT_TEXT,
                relations=(pda.RelationTag("parent-1", "변형"),),
            ),
            _rec(
                "problem_bank_rephrased_v0",
                "c-changed",
                "다른 텍스트",
                relations=(pda.RelationTag("parent-1", "변형"),),
            ),
            _rec("problem_bank_rephrased_v0", "c-no-parent", "발문", relations=()),
            _rec(
                "problem_bank_rephrased_v0",
                "c-orphan",
                "발문",
                relations=(pda.RelationTag("없음", "변형"),),
            ),
        )
        report = pda.measure_rephrase_noop_defect(self._corpora(records))
        assert report.total == 5
        assert report.measurable_count == 3
        assert report.unchanged_rate == pytest.approx(2 / 3)

    def test_build_report_integrates_rephrase_noop(self) -> None:
        # build_report가 자동으로 QUAL-03 측정을 계산해 DuplicationReport에 싣는지 배선 확인.
        child = _rec(
            "problem_bank_rephrased_v0",
            "child-1",
            self._PARENT_TEXT,
            relations=(pda.RelationTag("parent-1", "변형"),),
        )
        report = pda.build_report(
            self._corpora((child,)), demo_pool=frozenset(), demo_pool_status="파일없음"
        )
        assert report.rephrase_noop.target_corpus == "problem_bank_rephrased_v0"
        assert report.rephrase_noop.unchanged_count == 1
        rendered = pda.render_report(report)
        assert "QUAL-03" in rendered
        assert "무변화" in rendered
        payload = pda.report_to_json(report)
        assert payload["qual03_rephrase_noop_direct_measurement"]["unchanged_count"] == 1


# ──────────────────────────────────────────────────────────────────────────
# CLI — exit 0/2(게이트 아님)·JSON 결정론
# ──────────────────────────────────────────────────────────────────────────
def _cli_corpus_root(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    dup_text = "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오."
    _write_corpus(root, "problem_bank_alpha", [_problem_json(slug="s1", question_text=dup_text)])
    _write_corpus(root, "problem_bank_beta", [_problem_json(slug="s2", question_text=dup_text)])
    return root


def test_cli_exit_zero_even_when_real_duplicates_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _cli_corpus_root(tmp_path)
    rc = pda.main(["--corpus-root", str(root), "--seed-demo-path", str(tmp_path / "absent.py")])
    captured = capsys.readouterr()
    assert rc == pda._EXIT_OK
    assert "실중복 확정: 1쌍" in captured.out
    assert "데모 시드 스크립트 없음" in captured.err


def test_cli_exit_two_when_corpus_root_empty(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    rc = pda.main(["--corpus-root", str(empty_root)])
    assert rc == pda._EXIT_INPUT_ERROR


def test_cli_exit_two_on_named_corpus_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _cli_corpus_root(tmp_path)
    rc = pda.main(["--corpus-root", str(root), "--corpus", "problem_bank_ghost"])
    captured = capsys.readouterr()
    assert rc == pda._EXIT_INPUT_ERROR
    assert "데이터없음" in captured.out
    assert "코퍼스 파일 없음" in captured.err


def test_cli_json_artifact_is_deterministic(tmp_path: Path) -> None:
    root = _cli_corpus_root(tmp_path)
    out_a = tmp_path / "out" / "a.json"
    out_b = tmp_path / "out" / "b.json"
    for target in (out_a, out_b):
        rc = pda.main(["--corpus-root", str(root), "--json", str(target)])
        assert rc == pda._EXIT_OK
    assert out_a.read_bytes() == out_b.read_bytes()
    payload = json.loads(out_a.read_text(encoding="utf-8"))
    assert payload["t2_real_duplicates"]["confirmed_count"] == 1
    assert payload["t1_slug_collision"]["current_count"] == 0
    assert payload["t3_verify_conditions_signature"]["computed"] is False


def test_cli_warns_but_does_not_gate_when_seed_demo_missing(tmp_path: Path) -> None:
    """데모 시드 스크립트 부재는 보조 축 — exit 2로 막지 않는다(경고만)."""
    root = _cli_corpus_root(tmp_path)
    rc = pda.main(["--corpus-root", str(root), "--seed-demo-path", str(tmp_path / "nope.py")])
    assert rc == pda._EXIT_OK


def test_cli_qual03_section_present_and_graceful_without_target_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """QUAL-03 §7이 CLI 출력에 배선돼 있고, rephrased_v0가 없는 코퍼스 루트에서도 크래시 없이
    "측정 불가"를 정직하게 표기하는지(exit 0 유지) 확인한다."""
    root = _cli_corpus_root(tmp_path)  # problem_bank_alpha/beta뿐 — rephrased_v0 없음
    rc = pda.main(["--corpus-root", str(root), "--seed-demo-path", str(tmp_path / "absent.py")])
    captured = capsys.readouterr()
    assert rc == pda._EXIT_OK
    assert "QUAL-03" in captured.out
    assert "측정 불가" in captured.out


# ──────────────────────────────────────────────────────────────────────────
# 실제 코퍼스 스냅샷 — QUAL-01(2026-08-10) → QUAL-02 → PB-13 회수 → QUAL-07(2026-09-12) 실측 고정
# ──────────────────────────────────────────────────────────────────────────
def test_real_corpus_snapshot_t1_resolved_and_t2_zero_pairs_after_qual07() -> None:
    """실제 `data/corpus/` 전수 스캔 — QUAL-01(9쌍)→QUAL-02 은퇴→PB-13 회수(71쌍)→QUAL-07
    처분까지의 현행 상태를 동결한다.

    T1: 원 설계 문서(미병합 브랜치, 2026-08-03)의 392건이 QUAL-01 재측정에서 0건(해소됨·원인 미조사).
    T2 이력:
      · QUAL-01(2026-08-10) 실중복 9쌍 확정 → QUAL-02(2026-08-11) 쌍별 판정·9레코드 은퇴 → 0쌍.
      · PB-13(2026-09-01) 고립 저작분 회수로 신규 코퍼스 2종이 들어오며 **71쌍**으로 재발
        (problem_bank_highschool_quotient_rule_v0 ↔ problem_bank_university_calc1_chain_quotient_v0).
      · QUAL-07(2026-09-12) 처분 → **0쌍**. 처분 수단은 레코드 은퇴가 아니라 **생성기 파라미터
        공간의 서로소 분리 + 전건 재생성**이다 — 71쌍은 두 결정론 생성기가 같은 계수 범위·같은
        시드를 써서 대학 풀이 고교 풀의 부분집합이던 데서 왔고(실측), 문항만 은퇴시키면 재생성
        때 그대로 재발했을 자리다. 발문 동일 71쌍 밑에 **조건식(수학 실체) 동일 138건**이
        깔려 있었다는 것도 그때 드러났다 — 은퇴는 그 중 71건만 지웠을 것이다.
        (판정 기록: docs/data/problem_duplicate_disposition_2026-09.md)
    코퍼스 내용이 바뀌면(의도된 콘텐츠 작업) 이 테스트가 깨진다 — 그때는 값을 재실측해 갱신한다.
    """
    loads, problems = pda._resolve_loads(pda.DEFAULT_CORPUS_ROOT, None)
    if problems:
        pytest.skip(f"코퍼스 루트를 찾지 못함(이 환경엔 data/corpus가 없을 수 있음): {problems}")

    demo_pool = pda.demo_pool_corpora()
    report = pda.build_report(loads, demo_pool=demo_pool, demo_pool_status="파일확인됨")

    assert report.total_problems == 14034
    assert len(report.corpora) == 37

    # T1 — 해소됨.
    assert len(report.slug_collisions) == 0
    assert report.corpus_pairs_scanned == 666  # C(37,2) — PB-13 회수로 7종→37종

    # ── T2 감시 축 2종(QUAL-07이 acceptance ④로 **유지**를 지시한 단언) ─────────────
    # 이 둘은 현재 0쌍 상태에서 **공허 참**이다(빈 목록 위의 전칭·부분집합). 숨기지 않고
    # 적는다 — 목적이 "지금 무언가를 재는 것"이 아니라 **재발 시 성격을 즉시 가르는 것**이기
    # 때문이다. 71쌍 시절 이 두 축은 "기존 콘텐츠 무오염 · 학생 노출 0"을 뜻했고, 그래서
    # 시급도가 낮다고 판정할 수 있었다.
    #
    # **아래 `== 0`보다 먼저 둔 것은 의도다**: 재발 시 세 단언이 전부 깨지는데, 순서가
    # 반대면 "몇 쌍인가"만 보이고 "어느 축으로 번졌는가"는 보이지 않는다. 감시 축을 앞에
    # 두어야 실패 메시지가 성격을 지목한다.
    #   · 변별력 실측(QUAL-07 뮤테이션 M8·M9 — 둘 다 이 자리에서 RED):
    #     데모 풀 코퍼스 2종에 같은 발문을 심으면 첫 단언이, 고교 코퍼스와 제3 코퍼스가
    #     겹치게 심으면 둘째 단언이 각각 먼저 터진다.
    # 데모 풀 = generated_v0 · misconception_mc_v0 · problem_bank_v1.
    assert not any(pair.demo_pool_co_exposed for pair in report.duplicate_pairs)
    assert {frozenset((pair.corpus_a, pair.corpus_b)) for pair in report.duplicate_pairs} <= {
        frozenset(
            (
                "problem_bank_highschool_quotient_rule_v0",
                "problem_bank_university_calc1_chain_quotient_v0",
            )
        )
    }

    # T2 수치 — QUAL-07 처분 반영 후 71쌍 → 0쌍.
    assert report.duplicate_pair_count == 0
    assert len(report.duplicate_pairs_same_format) == 0
    assert len(report.duplicate_pairs_diff_format) == 0

    # 은퇴한 9레코드가 실제로 코퍼스에서 사라졌는지 슬러그 단위로 재확인(재유입 가드).
    all_slugs = {record.slug for load in loads for record in load.records}
    retired = {
        "wm-skel-92cd1ba2bbf5",  # 쌍9 은퇴 측(유지 측 wm-quad-eq-larger-root는 잔존해야 함)
        "wm-calc-extmc-bd21cd8484d2-rephrased",
        "wm-calc-extv-bd21cd8484d2-rephrased",
        "wm-calc-extmc-cf788e51e0fd-rephrased",
        "wm-calc-extv-cf788e51e0fd-rephrased",
        "wm-calc-extmc-5c4a86d7a72a-rephrased",
        "wm-calc-extv-5c4a86d7a72a-rephrased",
        "wm-calc-extmc-cd86d461d1b1-rephrased",
        "wm-calc-extv-cd86d461d1b1-rephrased",
    }
    assert all_slugs & retired == set()
    assert "wm-quad-eq-larger-root" in all_slugs  # 쌍9 유지 판정 측(배선 4곳 실참조)은 보존


def test_real_corpus_snapshot_rephrase_noop_direct_measurement() -> None:
    """실제 `data/corpus/` 전수 스캔 — QUAL-03 직접 측정(2026-08-10) + QUAL-02 은퇴 반영을 고정한다.

    QUAL-03 실측(429건): 무변화 282 · 정상변화 147 · 부모미선언 0 · 고아참조 0. QUAL-02(2026-08-11)가
    그중 실중복 확정 무변화 사본 8건을 은퇴 제거해 현행은 421건: 무변화 274 · 정상변화 147(불변) ·
    부모미선언 0 · 고아참조 0(은퇴 8건은 피참조 0이라 고아를 만들지 않음 — 제거 전 전수 grep 확인).
    QUAL-01의 간접 하한(lineage_excluded_pair_count)과 **정확히 일치**하는 성질은 은퇴 후에도
    유지된다(무변화 274 == 계보 제외 274 — 모든 관계가 1:1이고 부모가 항상 다른 코퍼스
    (generated_v0)에 있기 때문 — render_report §7 참고).
    코퍼스 내용이 바뀌면(의도된 콘텐츠 작업) 이 테스트가 깨진다 — 그때는 값을 재실측해 갱신한다.
    """
    loads, problems = pda._resolve_loads(pda.DEFAULT_CORPUS_ROOT, None)
    if problems:
        pytest.skip(f"코퍼스 루트를 찾지 못함(이 환경엔 data/corpus가 없을 수 있음): {problems}")

    report = pda.build_report(loads, demo_pool=frozenset(), demo_pool_status="파일없음")
    noop = report.rephrase_noop

    assert noop.target_corpus == "problem_bank_rephrased_v0"
    assert noop.total == 421
    assert noop.unchanged_count == 274
    assert noop.changed_count == 147
    assert noop.no_parent_declared_count == 0
    assert noop.orphan_parent_count == 0
    assert noop.measurable_count == 421
    assert noop.unchanged_rate == pytest.approx(274 / 421)

    # QUAL-01 간접 하한과의 교차검증 — 이 코퍼스 상태에서는 정확히 일치(정직 회계 비교 대상).
    assert report.lineage_excluded_pair_count == noop.unchanged_count == 274

    # 421건 전부 부모가 problem_bank_generated_v0에 있다(실측 — 다른 코퍼스로의 rephrase는 없음).
    parent_corpora = {r.parent_corpus for r in noop.records}
    assert parent_corpora == {"problem_bank_generated_v0"}

    # 모든 rephrased_v0 레코드가 정확히 1개 관계만 선언한다(측정 함수의 "첫 번째만 사용" 결정이
    # 현재 데이터에 영향을 주지 않는다는 전제 — 위 pure-logic 테스트가 그 결정 자체를 고정한다).
    rephrased_load = next(ld for ld in loads if ld.name == "problem_bank_rephrased_v0")
    assert all(len(r.relations) == 1 for r in rephrased_load.records)
