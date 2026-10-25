"""학교급 경계 선수 연결 밀도 관측 리포트 테스트 — 결정론·정직 회계·변별력 동결(hermetic).

대상: `whymath_backend.harness.cross_school_connectivity_report`(CUR-06 acceptance). 실 DB·LLM·
네트워크 0 — 소형 픽스처(그래프 리터럴)로 검증한다. 실 코퍼스 대상 acceptance① 재현 테스트
1건만 실제 `data/corpus/atom_graph_v1/graph.json`을 읽는다(회귀 감시·정확 임계값 단언 — S4-01이
경계 엣지를 정본에 병합하면 이 수치가 *의도적으로* 바뀌므로 그때 이 핀을 갱신한다).

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"):
  - 경계 엣지 1건을 넣고 빼면 고등→중학 도달 가능 수가 양방향으로 움직인다(acceptance④). 같은
    1건을 같은 학교급 *내부*에 넣으면 움직이지 않는다 — 학교급을 가르는 지표라는 증거.
  - 총 엣지 수만 세는 지표는 경계 1건 가감에 도달 비율이 움직이는 것과 달리 *경계 아닌 엣지*
    가감에도 똑같이 움직인다(대조군) — 그래서 총량 지표는 위장이라는 acceptance④의 근거.
  - 방향: 선수 방향과 반대(고등→중학, 역방향) 엣지는 도달로 세지 않는다.
  - 깊이: 사슬이 `MAX_PREREQUISITE_DEPTH`를 넘으면 그 깊이 예산에서는 빠지고 무제한에서만 잡힌다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import cross_school_connectivity_report as csc
from whymath_backend.l2.prerequisite_recommendation import MAX_PREREQUISITE_DEPTH

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FACTS = json.loads((_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8"))

_E = tuple[str, str]  # (from_code, to_code)


def _payload(
    concepts: dict[str, str | None],
    edges: list[_E],
    *,
    flags: dict[_E, bool] | None = None,
    subtypes: dict[_E, str] | None = None,
    bands: dict[str, str | None] | None = None,
) -> dict[str, object]:
    """`{code: school_level}` + `(from, to)` 목록 → graph.json 형태 payload."""
    out_edges: list[dict[str, object]] = []
    for frm, to in edges:
        row: dict[str, object] = {"from_code": frm, "to_code": to, "relation": "prerequisite"}
        if flags is not None:
            row["school_link"] = flags.get((frm, to), False)
        if subtypes is not None and (frm, to) in subtypes:
            row["relation_subtype"] = subtypes[(frm, to)]
        out_edges.append(row)
    out_concepts: list[dict[str, object]] = []
    for code, level in concepts.items():
        row2: dict[str, object] = {"code": code, "school_level": level}
        if bands is not None:
            row2["grade_band"] = bands.get(code)
        out_concepts.append(row2)
    return {"concepts": out_concepts, "edges": out_edges}


def _report(payload: dict[str, object]) -> csc.ConnectivityReport:
    return csc.build_report(csc.load_corpus_graph(payload))


def _cell(report: csc.ConnectivityReport, start: str, target: str) -> csc.ReachCell:
    (cell,) = [c for c in report.reach_cells if (c.start_level, c.target_level) == (start, target)]
    return cell


# 중학 M1 ← 고등 H1 ← 고등 H2 (H1·H2 모두 고등). 경계 엣지 M1→H1 1건.
_BASE_CONCEPTS: dict[str, str | None] = {"M1": "중학", "H1": "고등", "H2": "고등", "H3": "고등"}


# ──────────────────────────────────────────────────────────────────────────
# 1. 로더 — 정상·정직 실패
# ──────────────────────────────────────────────────────────────────────────
def test_load_filters_non_prerequisite_relations() -> None:
    payload = _payload({"A": "초등", "B": "초등"}, [("A", "B")])
    edges = payload["edges"]
    assert isinstance(edges, list)
    edges.append({"from_code": "A", "to_code": "B", "relation": "similar_to"})
    graph = csc.load_corpus_graph(payload)
    assert len(graph.edges) == 1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"items": []},
        {"concepts": [{"name": "code 없음"}]},
        {"concepts": [{"code": "A"}, {"code": "A"}], "edges": []},  # code 중복
        {"concepts": [{"code": "A"}], "edges": "not-a-list"},
        {"concepts": [{"code": "A"}], "edges": [{"to_code": "A", "relation": "prerequisite"}]},
        {"concepts": [{"code": "A"}], "edges": [{"from_code": "A", "relation": "prerequisite"}]},
        # 끝점이 개념에 없음 — 건너뛰면 분모가 줄어 경계 밀도가 거짓으로 보인다.
        {
            "concepts": [{"code": "A"}],
            "edges": [{"from_code": "A", "to_code": "Z", "relation": "prerequisite"}],
        },
    ],
)
def test_load_rejects_malformed_payload(payload: object) -> None:
    with pytest.raises(ValueError):
        csc.load_corpus_graph(payload)


# ──────────────────────────────────────────────────────────────────────────
# 2. 학교급 쌍별 밀도
# ──────────────────────────────────────────────────────────────────────────
def test_pair_counts_split_intra_and_boundary() -> None:
    report = _report(_payload(_BASE_CONCEPTS, [("M1", "H1"), ("H1", "H2"), ("H2", "H3")]))
    assert report.edge_total == 3
    assert report.intra_level_total == 2
    assert report.boundary_edge_total == 1
    assert report.backward_boundary_total == 0
    assert dict(report.level_pair_counts) == {("중학", "고등"): 1, ("고등", "고등"): 2}
    assert report.boundary_rate == pytest.approx(1 / 3)


def test_backward_boundary_edge_is_counted_separately() -> None:
    report = _report(_payload(_BASE_CONCEPTS, [("H1", "M1")]))  # 선수가 더 높은 학교급
    assert report.boundary_edge_total == 1
    assert report.backward_boundary_total == 1


def test_unknown_school_level_is_not_folded_into_intra() -> None:
    """학교급을 모르는 끝점은 '같은 학교급'으로 접히지 않는다(모른다 ≠ 아니다)."""
    report = _report(_payload({"A": "초등", "B": None, "C": None}, [("A", "B"), ("B", "C")]))
    assert report.boundary_edge_total == 1  # 초등→미상
    assert report.intra_level_total == 1  # 미상→미상(둘 다 모름 — 같은 라벨)
    assert ("초등", "미상") in report.level_pair_counts


def test_empty_graph_has_no_rates_and_does_not_crash() -> None:
    report = _report({"concepts": [], "edges": []})
    assert report.boundary_rate is None
    assert all(c.population == 0 and c.rate_any is None for c in report.reach_cells)


# ──────────────────────────────────────────────────────────────────────────
# 3. 학년군 경계
# ──────────────────────────────────────────────────────────────────────────
def test_grade_band_pairs_and_unknown_are_counted_apart() -> None:
    concepts: dict[str, str | None] = {"A": "고등", "B": "고등", "C": "고등", "D": "고등"}
    bands: dict[str, str | None] = {"A": "고1", "B": "고2", "C": "고2", "D": None}
    report = _report(_payload(concepts, [("A", "B"), ("B", "C"), ("C", "D")], bands=bands))
    assert dict(report.grade_band_pair_counts) == {("고1", "고2"): 1}  # 고2→고2는 경계 아님
    assert report.grade_band_unknown_edge_total == 1  # C→D(D 학년군 모름)


# ──────────────────────────────────────────────────────────────────────────
# 4. school_link 이중 확인
# ──────────────────────────────────────────────────────────────────────────
def test_school_link_agreement_counts_both_flag_only_endpoint_only() -> None:
    concepts: dict[str, str | None] = {"M1": "중학", "H1": "고등", "H2": "고등", "H3": "고등"}
    edges = [("M1", "H1"), ("M1", "H2"), ("H1", "H3"), ("H2", "H3")]
    flags = {("M1", "H1"): True, ("H1", "H3"): True, ("H2", "H3"): True}
    report = _report(_payload(concepts, edges, flags=flags))
    assert report.flag_known_total == 4
    assert report.flag_both == 1  # M1→H1
    # 비대칭 픽스처(2≠1) — 두 카운터가 뒤바뀌어도 통과하는 대칭 위장을 막는다.
    assert report.flag_only == 2  # H1→H3·H2→H3 (내부인데 플래그)
    assert report.endpoint_only == 1  # M1→H2 (경계인데 플래그 없음)


def test_school_link_absent_in_source_is_not_read_as_clean() -> None:
    """필드가 소스에 없으면 '불일치 0'이 아니라 '확인 불가'로 표기된다(flag_known_total=0)."""
    report = _report(_payload(_BASE_CONCEPTS, [("M1", "H1")]))  # flags=None → 필드 없음
    assert report.flag_known_total == 0
    assert "이중 확인 **불가**" in csc.render_report(report)


def test_boundary_label_total_is_recorded_apart_from_authority() -> None:
    subtypes = {("M1", "H1"): "학교급간(추정)", ("H1", "H2"): "학년간", ("H2", "H3"): "소단원내"}
    report = _report(
        _payload(
            _BASE_CONCEPTS,
            [("M1", "H1"), ("H1", "H2"), ("H2", "H3")],
            flags={("M1", "H1"): True},
            subtypes=subtypes,
        )
    )
    assert report.boundary_label_total == 2  # 학년간 + 학교급간(추정)
    assert report.boundary_edge_total == 1  # 판정 권위는 양끝점 — 라벨 합과 다를 수 있다
    assert dict(report.flagged_subtype_counts) == {"학교급간(추정)": 1}


# ──────────────────────────────────────────────────────────────────────────
# 5. 하향 도달 — 변별력(acceptance④)
# ──────────────────────────────────────────────────────────────────────────
def _high_to_mid(report: csc.ConnectivityReport) -> csc.ReachCell:
    return _cell(report, "고등", "중학")


def test_adding_one_boundary_edge_moves_reach_and_removing_moves_it_back() -> None:
    intra = [("H1", "H2"), ("H2", "H3")]
    without = _report(_payload(_BASE_CONCEPTS, intra))
    with_edge = _report(_payload(_BASE_CONCEPTS, [("M1", "H1"), *intra]))

    assert _high_to_mid(without).reached_any == 0
    # M1→H1: H1(1홉)·H2(2홉)·H3(3홉)이 모두 사슬을 거슬러 M1에 닿는다.
    cell = _high_to_mid(with_edge)
    assert cell.population == 3
    assert cell.reached_any == 3
    assert cell.reached_within == (1, 2, 3)  # DEPTH_BUDGETS=(1,2,5) 순서
    # 제거하면 원상 복귀.
    assert _high_to_mid(_report(_payload(_BASE_CONCEPTS, intra))).reached_any == 0


def test_intra_level_edges_move_total_count_but_not_boundary_density() -> None:
    """대조군 — 총 엣지 수는 경계 아닌 엣지에도 움직이므로 총량 지표는 경계를 가르지 못한다."""
    before = _report(_payload(_BASE_CONCEPTS, [("M1", "H1"), ("H1", "H2")]))
    after = _report(_payload(_BASE_CONCEPTS, [("M1", "H1"), ("H1", "H2"), ("H2", "H3")]))
    assert after.edge_total == before.edge_total + 1  # 총량 지표는 반응한다(위장의 근거)
    assert after.boundary_edge_total == before.boundary_edge_total  # 경계 밀도는 불변


def test_internal_chain_disconnected_from_boundary_does_not_count_as_reach() -> None:
    """경계 엣지에 이어지지 않은 고등 내부 사슬(H3→H4)은 도달에 들어가지 않는다."""
    concepts = _BASE_CONCEPTS | {"H4": "고등"}
    report = _report(_payload(concepts, [("M1", "H1"), ("H3", "H4")]))
    assert _high_to_mid(report).reached_any == 1  # H1만


def test_reversed_boundary_edge_is_not_counted_as_reach() -> None:
    forward = _report(_payload(_BASE_CONCEPTS, [("M1", "H1")]))
    reversed_ = _report(_payload(_BASE_CONCEPTS, [("H1", "M1")]))  # 고등이 중학의 선수 — 역방향
    assert _high_to_mid(forward).reached_any == 1
    assert _high_to_mid(reversed_).reached_any == 0


def test_depth_budget_excludes_chains_longer_than_max_depth() -> None:
    chain_len = MAX_PREREQUISITE_DEPTH + 1
    concepts: dict[str, str | None] = {"M1": "중학"}
    concepts.update({f"H{i}": "고등" for i in range(chain_len)})
    # M1 → H{chain_len-1} → … → H1 → H0: H0에서 M1까지 정확히 chain_len 홉.
    edges = [("M1", f"H{chain_len - 1}")]
    edges += [(f"H{i + 1}", f"H{i}") for i in range(chain_len - 1)]
    cell = _high_to_mid(_report(_payload(concepts, edges)))
    assert cell.population == chain_len
    assert cell.reached_any == chain_len  # 무제한: 전부 닿음
    max_idx = csc.DEPTH_BUDGETS.index(MAX_PREREQUISITE_DEPTH)
    assert cell.reached_within[max_idx] == chain_len - 1  # H0은 예산 밖


def test_depth_budgets_reuse_max_prerequisite_depth_single_source() -> None:
    assert csc.DEPTH_BUDGETS == (1, 2, MAX_PREREQUISITE_DEPTH)


def test_reach_passes_through_intermediate_school_level() -> None:
    """대학→고등→중학 사슬: 대학 노드는 중학에 닿고(고등을 통과), 학교급 쌍 직접 엣지는 없다."""
    concepts: dict[str, str | None] = {"M1": "중학", "H1": "고등", "U1": "대학"}
    report = _report(_payload(concepts, [("M1", "H1"), ("H1", "U1")]))
    assert _cell(report, "대학", "중학").reached_within[:2] == (0, 1)  # 1홉엔 H1뿐, 2홉에 M1
    assert _cell(report, "대학", "고등").reached_within[0] == 1


def test_cycle_in_data_terminates() -> None:
    report = _report(_payload(_BASE_CONCEPTS, [("H1", "H2"), ("H2", "H1"), ("M1", "H1")]))
    assert _high_to_mid(report).reached_any == 2  # H1·H2 — 사이클에도 종료


# ──────────────────────────────────────────────────────────────────────────
# 6. 결정론·렌더·JSON·CLI
# ──────────────────────────────────────────────────────────────────────────
def test_build_report_is_deterministic_regardless_of_input_order() -> None:
    edges = [("M1", "H1"), ("H1", "H2"), ("H2", "H3")]
    a = _report(_payload(_BASE_CONCEPTS, edges))
    b = _report(_payload(dict(reversed(list(_BASE_CONCEPTS.items()))), list(reversed(edges))))
    assert csc.dump_json(a) == csc.dump_json(b)


def test_render_states_not_a_gate_and_marks_core_row() -> None:
    text = csc.render_report(_report(_payload(_BASE_CONCEPTS, [("M1", "H1")])))
    assert "게이트가 아니다" in text
    assert "**고등** | **중학**" in text


def test_json_marks_non_gate_and_exposes_reach_rows() -> None:
    data = csc.report_to_json(_report(_payload(_BASE_CONCEPTS, [("M1", "H1")])))
    assert data["is_gate"] is False
    assert data["depth_budgets"] == list(csc.DEPTH_BUDGETS)
    row = next(
        r for r in data["reach"] if (r["start_level"], r["target_level"]) == ("고등", "중학")
    )
    assert (row["population"], row["reached_any"]) == (3, 1)  # H1만 M1에 닿는다
    assert set(row["reached_within"]) == {str(d) for d in csc.DEPTH_BUDGETS}


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_main_exit_0_even_when_boundary_density_is_zero(tmp_path: Path) -> None:
    """게이트가 아니다 — 경계 0건이어도 exit 1이 아니라 0."""
    corpus = _write(tmp_path, _payload({"A": "초등", "B": "초등"}, [("A", "B")]))
    assert csc.main(["--corpus", str(corpus)]) == 0


def test_main_exit_2_on_missing_or_malformed_corpus(tmp_path: Path) -> None:
    assert csc.main(["--corpus", str(tmp_path / "없음.json")]) == 2
    bad = _write(
        tmp_path,
        {
            "concepts": [{"code": "A"}],
            "edges": [{"from_code": "A", "to_code": "Z", "relation": "prerequisite"}],
        },
    )
    assert csc.main(["--corpus", str(bad)]) == 2


def test_main_writes_json_artifact(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _payload(_BASE_CONCEPTS, [("M1", "H1")]))
    out = tmp_path / "sub" / "out.json"
    assert csc.main(["--corpus", str(corpus), "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["boundary_edge_total"] == 1


# ──────────────────────────────────────────────────────────────────────────
# 7. 실 코퍼스 — acceptance① 재현(회귀 감시·정확 단언)
# ──────────────────────────────────────────────────────────────────────────
def test_real_corpus_reproduces_pinned_acceptance_one_numbers() -> None:
    """정본 2,278엣지 중 경계 47·내부 2,231, 고→대 25, school_link 47(플래그 없는 경계 0).

    KG-10 ②(2026-10-20): KG-09 교체분의 경계 신규 10건을 AI 2인 블라인드 검수해 반려 3
    (중학 인수분해 → CALC1-C03·CALC1-P01·10공수1-01-03-2)·교체 1(→CALC1-P21의 출발을 고등
    10공수1-01-03-1로)을 정본 xlsx에 반영·재생성했다. 중→대 3건이 사라지고 고→대가 25가 됐다.

    KG-09(2026-10-20)가 통합마스터 v3로 원자 백본을 재생성해 엣지 205건이 교체됐다(노드·엣지
    총수는 2,683·2,234로 불변). 교체분이 경계 엣지 6건을 새로 들였다 — 초→고 1(비율의 의미),
    중→고 +2(13), 중→대 3(인수분해 → 대학 미적분 극한·부정형·부분분수). 중→대 3건은 원천 xlsx에
    학교급간 표기가 없어 `school_link` 플래그가 없다(endpoint_only 3 — 아래 이중 확인에 기록).

    S4-60(2026-10-09) 핀: 경계 44(20 + 고→대 24)·내부 2,190·플래그 44/0/0·라벨 합 40·
    고→중 (925, (9, 35, 123), 387). 그 이전(병합 전)은 2,210·경계 20·고→대 0·플래그 20이었다.

    KG-12(2026-10-20): ① 대학 내부 체인 수리(제거 12·반전 4 — 전부 대학→대학 내부)로 2,231→2,219,
    ③ 낱말매칭 승격 v2 59건(대학→대학)으로 2,278. 경계 47·플래그·라벨 합은 불변이고 대학→대학만
    481→528. 대학→고등 도달은 198→160 — 되감기 엣지 제거로 2차 저작분이 체인에서 떨어졌다(새 뿌리
    5·보완 배선 후속 KG-13); 1홉·2홉 도달은 승격 엣지로 44→47·80→91.
    """
    payload = json.loads(csc.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    report = csc.build_report(csc.load_corpus_graph(payload))

    assert report.edge_total == _FACTS["atom_graph.edges"]
    assert report.boundary_edge_total == 47  # 50(KG-09) − 반려 3 → 47/2,278 = 2.06%
    assert (
        report.intra_level_total == 2231
    )  # KG-09 2,190 − 6 → 2,184 · KG-12 대학 내부 −12 + 59 → 2,231
    assert report.backward_boundary_total == 0
    assert dict(report.level_pair_counts) == {
        ("초등", "초등"): 537,
        ("초등", "중학"): 9,
        ("초등", "고등"): 1,  # KG-09 — 6수02-03-1 비율의 의미 → 12수문04-01-2
        ("중학", "중학"): 241,
        ("중학", "고등"): 12,  # KG-10 ② 반려 1(9수02-19-2 → 10공수1-01-03-2)
        ("고등", "고등"): 925,  # corpus-pin: 측정값 — 고등→고등 엣지 수(고등 노드 수와 우연 일치)
        ("고등", "대학"): 25,  # S4-60 병합분 24 + KG-10 ② 교체 1(10공수1-01-03-1 → CALC1-P21)
        ("대학", "대학"): 528,  # KG-12 ① 제거 12 · ③ 승격 v2 59 → 481 − 12 + 59
    }

    # 이중 확인: 플래그 47건 = 양끝점 유도 47건(both 47·flag only 0·endpoint only 0) — KG-09의
    # endpoint only 3(중→대·학교급간 표기 없음)은 KG-10 ② 검수로 반려 2·교체(표기 Y) 1이 돼 0이 됐다.
    assert (report.flag_both, report.flag_only, report.endpoint_only) == (47, 0, 0)
    # 코퍼스 내부 라벨 불일치(기록): S4-60 시점 40 ≠ 44. KG-09 교체 후 라벨 합 35 ≠ 경계 50(KG-10 ② 후 47) —
    # 교체된 205건 가운데 라벨이 비는 행이 늘었다(라벨 축은 관측 전용·게이트 아님).
    assert report.boundary_label_total == 35

    # 하향 도달 — 고등→중학이 핵심 행. 대학은 아무 하위 학교급에도 닿지 못한다.
    core = _cell(report, "고등", "중학")
    assert (core.population, core.reached_within, core.reached_any) == (
        _FACTS["atom_graph.nodes_high"],
        (11, 42, 134),
        307,
    )
    # 대학은 더 이상 섬이 아니다: 대학 1,069 중 160이 고등 선수에 닿는다(독립 BFS 실측과 일치 —
    # KG-12 ① 체인 수리 전 198).
    uni_to_high = _cell(report, "대학", "고등")
    assert (uni_to_high.population, uni_to_high.reached_within, uni_to_high.reached_any) == (
        _FACTS["atom_graph.nodes_university"],
        (25, 47, 91),  # KG-10 ② 교체 엣지가 1홉 +1 · KG-12 ③ 승격 v2가 2홉·3홉 +3·+11
        160,
    )
