"""QA 파이프라인 오케스트레이터 테스트 (ARCH-21) — 축별 헬퍼 단위테스트 + CLI 통합 1건.

전체 `main()`을 매번 돌리면 defect_detection_eval·coach_prose_leak_eval 두 축이 무거워
테스트가 느려진다 — 그래서 축별 헬퍼(`_axis_*`)를 개별 단위테스트하고, 무거운 3축
(misconception_crosslink_demotion·coach_prose_leak·defect_injection_demotion)은 하위
harness 모듈의 함수를 monkeypatch해 결정론·경량으로 게이트 판정 로직만 검증한다. CLI
통합테스트(`test_cli_main_runs_end_to_end_and_writes_valid_json`)만 실제로 `main([])`를
끝까지 돌려 exit code·JSON 유효성을 확인한다(느려도 필수 — acceptance).

`TestAxisDefectReportIntake`(RPT-01 8번째 축)는 실 PG 없이 세션 팩토리를 가짜로 주입해
"미배선"(no_snapshot·table_exists=False)·"DB 도달 불가"(no_snapshot·table_exists=None,
ARCH-23)·"0건 접수"(ok+count=0)·"그 외 DB 오류"(error로 전파) 네 상태를 결정론적으로
재현한다 — 실 PG로의 왕복(진짜 gen_random_uuid()/now())은
`tests/backend/api/test_reports_integration.py`가 담당한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from whymath_backend.harness import qa_pipeline as qp
from whymath_backend.harness.banned_words_pii_eval import BannedWordsPiiReport
from whymath_backend.harness.coach_prose_leak_eval import ProseLeakReport
from whymath_backend.harness.crosslink_demotion_eval import CrosslinkDemotionReport
from whymath_backend.harness.defect_detection_eval import DetectionReport

# ──────────────────────────────────────────────────────────────────────────
# 경로 헬퍼
# ──────────────────────────────────────────────────────────────────────────


def test_default_corpus_root_appends_data_corpus(tmp_path: Path) -> None:
    assert qp._default_corpus_root(tmp_path) == tmp_path / "data" / "corpus"


def test_repo_root_points_to_real_repo() -> None:
    root = qp._repo_root()
    assert (root / "src" / "backend" / "whymath_backend" / "harness" / "qa_pipeline.py").is_file()


def test_load_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    assert qp._load_jsonl(p) == [{"a": 1}, {"a": 2}]


# ──────────────────────────────────────────────────────────────────────────
# 축 1 — corpus_audit(문항 감사·스냅샷 재검산)
# ──────────────────────────────────────────────────────────────────────────


class TestAxisCorpusAudit:
    def test_no_snapshot_is_not_a_gate_failure(self, tmp_path: Path) -> None:
        result = qp._axis_corpus_audit(tmp_path)
        assert result.status == "no_snapshot"
        assert result.detail == {"snapshot_count": 0}

    def test_found_snapshot_summarizes(self, tmp_path: Path) -> None:
        docs_data = tmp_path / "docs" / "data"
        docs_data.mkdir(parents=True)
        (docs_data / "corpus_audit_x.jsonl").write_text(
            '{"problem_id": "a", "verdict": "ok"}\n'
            '{"problem_id": "b", "verdict": "defect", "defect_class": "answer_error"}\n',
            encoding="utf-8",
        )
        result = qp._axis_corpus_audit(tmp_path)
        assert result.status == "ok"
        assert result.detail["snapshot_count"] == 1
        snap = result.detail["snapshots"]["corpus_audit_x.jsonl"]
        assert snap["n"] == 2
        assert snap["defects"] == 1
        assert snap["defect_rate_upper_bound"] > 0.0

    def test_multiple_snapshots_all_discovered(self, tmp_path: Path) -> None:
        docs_data = tmp_path / "docs" / "data"
        docs_data.mkdir(parents=True)
        (docs_data / "corpus_audit_a.jsonl").write_text(
            '{"problem_id": "a", "verdict": "ok"}\n', encoding="utf-8"
        )
        (docs_data / "corpus_audit_b.jsonl").write_text(
            '{"problem_id": "b", "verdict": "ok"}\n', encoding="utf-8"
        )
        result = qp._axis_corpus_audit(tmp_path)
        assert result.status == "ok"
        assert result.detail["snapshot_count"] == 2
        assert set(result.detail["snapshots"].keys()) == {
            "corpus_audit_a.jsonl",
            "corpus_audit_b.jsonl",
        }


# ──────────────────────────────────────────────────────────────────────────
# 축 2 — equivalence_canonicalize(수식 동치 DSL 폐쇄성)
# ──────────────────────────────────────────────────────────────────────────


class TestAxisEquivalenceCanonicalize:
    def test_ok_reads_top_level_and_nested_conditions(self, tmp_path: Path) -> None:
        bank = tmp_path / "problem_bank_a"
        bank.mkdir()
        rows = [
            {"slug": "p1", "conditions": "x**2 - 1 = 0"},  # 최상위
            {"slug": "p2", "verify": {"conditions": "x + 1 = 0"}},  # verify.conditions(실측 형태)
            {"slug": "p3"},  # conditions 없음 — 스킵(에러 아님)
        ]
        (bank / "problems.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        result = qp._axis_equivalence_canonicalize(tmp_path)
        assert result.status == "ok"
        assert result.detail == {"total_conditions_checked": 2, "violations": 0}

    def test_gate_fail_on_dsl_violation(self, tmp_path: Path) -> None:
        bank = tmp_path / "problem_bank_a"
        bank.mkdir()
        rows = [{"slug": "p1", "verify": {"conditions": "largest_root(2, 8) == 8"}}]
        (bank / "problems.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        result = qp._axis_equivalence_canonicalize(tmp_path)
        assert result.status == "gate_fail"
        assert result.detail == {"total_conditions_checked": 1, "violations": 1}

    def test_no_matching_corpora_reports_zero_checked(self, tmp_path: Path) -> None:
        result = qp._axis_equivalence_canonicalize(tmp_path)
        assert result.status == "ok"
        assert result.detail == {"total_conditions_checked": 0, "violations": 0}

    @pytest.mark.parametrize("answer_kind", sorted(qp._NON_EQUATION_DSL_ANSWER_KINDS))
    def test_non_equation_dsl_answer_kinds_are_excluded_from_check(
        self, tmp_path: Path, answer_kind: str
    ) -> None:
        """S3-28: 확률/통계 전용 DSL(answer_kind별 별도 파서)은 등식 DSL 검사 대상이 아니다.

        실측(2026-08-03, 2026-09-10 재확인): 코퍼스 전수에서 위반이 전부 이 6종 —
        각자 이미 닫힌 파서(`l3/finite_probability.py`·`l3/verify_answer.py`의
        comma-list 파서)로 검증되므로 등식 sympify 폐쇄성 검사를 적용하면 필연적으로
        위반 오탐이 난다(코퍼스 결함 아님).
        """
        bank = tmp_path / "problem_bank_a"
        bank.mkdir()
        # 실제로 sympify 위반을 내는 형태(확률 미니 DSL·쉼표 숫자열) — exempt 안 됐다면
        # gate_fail이 났을 조건들. answer_kind가 상위/verify 어느 쪽에 있어도 동작해야 한다.
        rows = [
            {
                "slug": "p1",
                "answer_kind": answer_kind,
                "conditions": "space=dice(n=2,faces=6); event=sum==7",
            },
            {"slug": "p2", "verify": {"answer_kind": answer_kind, "conditions": "3,5,7,9"}},
        ]
        (bank / "problems.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        result = qp._axis_equivalence_canonicalize(tmp_path)
        assert result.status == "ok"
        assert result.detail == {"total_conditions_checked": 0, "violations": 0}

    def test_equation_answer_kind_violation_still_caught(self, tmp_path: Path) -> None:
        """비exempt answer_kind(또는 무지정)는 등식 DSL 검사가 그대로 적용된다(회귀 방지 —
        exempt 범위를 넓혀 진짜 결함까지 숨기지 않았는지 확인)."""
        bank = tmp_path / "problem_bank_a"
        bank.mkdir()
        rows = [
            {
                "slug": "p1",
                "verify": {
                    "answer_kind": "real_root_count",
                    "conditions": "largest_root(2, 8) == 8",
                },
            }
        ]
        (bank / "problems.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        result = qp._axis_equivalence_canonicalize(tmp_path)
        assert result.status == "gate_fail"
        assert result.detail == {"total_conditions_checked": 1, "violations": 1}


# ──────────────────────────────────────────────────────────────────────────
# 축 3 — concept_graph_reachability(원자 백본 그래프 atom_graph_v1)
# ──────────────────────────────────────────────────────────────────────────


def _write_atom_graph_fixture(
    corpus_root: Path, *, with_cycle: bool, with_dangling: bool = False
) -> None:
    concepts = [{"code": "atom.a"}, {"code": "atom.b"}]
    edges = [{"relation": "prerequisite", "from_code": "atom.a", "to_code": "atom.b"}]
    if with_cycle:
        edges.append({"relation": "prerequisite", "from_code": "atom.b", "to_code": "atom.a"})
    if with_dangling:
        edges.append({"relation": "prerequisite", "from_code": "atom.a", "to_code": "atom.missing"})
    graph_dir = corpus_root / "atom_graph_v1"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(
        json.dumps({"concepts": concepts, "edges": edges}, ensure_ascii=False), encoding="utf-8"
    )


class TestAxisConceptGraphReachability:
    def test_ok_on_clean_dag(self, tmp_path: Path) -> None:
        _write_atom_graph_fixture(tmp_path, with_cycle=False)
        result = qp._axis_concept_graph_reachability(tmp_path)
        assert result.status == "ok"
        assert result.detail == {
            "node_count": 2,
            "edge_count": 1,
            "cycle": None,
            "dangling_count": 0,
            "success": True,
        }

    def test_gate_fail_on_cycle(self, tmp_path: Path) -> None:
        _write_atom_graph_fixture(tmp_path, with_cycle=True)
        result = qp._axis_concept_graph_reachability(tmp_path)
        assert result.status == "gate_fail"
        assert result.detail["cycle"] is not None
        assert result.detail["success"] is False

    def test_gate_fail_on_dangling_endpoint(self, tmp_path: Path) -> None:
        _write_atom_graph_fixture(tmp_path, with_cycle=False, with_dangling=True)
        result = qp._axis_concept_graph_reachability(tmp_path)
        assert result.status == "gate_fail"
        assert result.detail["dangling_count"] == 1
        assert result.detail["success"] is False


# ──────────────────────────────────────────────────────────────────────────
# 축 4 — misconception_crosslink_demotion(오개념 crosswalk) — run() monkeypatch
# ──────────────────────────────────────────────────────────────────────────


class TestAxisMisconceptionCrosslinkDemotion:
    def test_ok_when_thresholds_met(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = CrosslinkDemotionReport(
            positive_total=10,
            positive_false_reject=0,
            cross_detected=100,
            cross_total=100,
            same_detected=0,
            same_total=10,
            kebabs_total=64,
            kebabs_decidable=64,
        )
        monkeypatch.setattr(qp.crosslink_demotion_eval, "run", lambda **_kwargs: (fake_report, []))
        result = qp._axis_misconception_crosslink_demotion()
        assert result.status == "ok"
        assert result.detail["false_reject_count"] == 0

    def test_gate_fail_on_positive_false_reject(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = CrosslinkDemotionReport(
            positive_total=10,
            positive_false_reject=1,
            cross_detected=100,
            cross_total=100,
            same_detected=0,
            same_total=10,
            kebabs_total=64,
            kebabs_decidable=64,
        )
        monkeypatch.setattr(qp.crosslink_demotion_eval, "run", lambda **_kwargs: (fake_report, []))
        result = qp._axis_misconception_crosslink_demotion()
        assert result.status == "gate_fail"
        assert result.detail["false_reject_count"] == 1

    def test_gate_fail_on_cross_lower_bound_below_floor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # cross 거부 0/10 → 하한이 _CROSS_REJECT_FLOOR(0.90) 미달.
        fake_report = CrosslinkDemotionReport(
            positive_total=10,
            positive_false_reject=0,
            cross_detected=0,
            cross_total=10,
            same_detected=0,
            same_total=10,
            kebabs_total=64,
            kebabs_decidable=64,
        )
        monkeypatch.setattr(qp.crosslink_demotion_eval, "run", lambda **_kwargs: (fake_report, []))
        result = qp._axis_misconception_crosslink_demotion()
        assert result.status == "gate_fail"
        assert result.detail["cross_lower_bound"] < qp.crosslink_demotion_eval._CROSS_REJECT_FLOOR


# ──────────────────────────────────────────────────────────────────────────
# 축 5 — coach_prose_leak(AI 출력 누설) — run_machine/summarize monkeypatch
# ──────────────────────────────────────────────────────────────────────────


class TestAxisCoachProseLeak:
    def test_ok_when_no_leak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = ProseLeakReport(
            defect_total=100, leaked=0, clean_total=100, false_blocked=0, by_cell={}
        )
        monkeypatch.setattr(qp.coach_prose_leak_eval, "run_machine", lambda _cases: [])
        monkeypatch.setattr(qp.coach_prose_leak_eval, "summarize", lambda _outcomes: fake_report)
        result = qp._axis_coach_prose_leak()
        assert result.status == "ok"
        assert result.detail["leak_upper_bound"] < qp._PROSE_MAX_LEAK_UPPER

    def test_gate_fail_on_high_leak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = ProseLeakReport(
            defect_total=100, leaked=100, clean_total=100, false_blocked=0, by_cell={}
        )
        monkeypatch.setattr(qp.coach_prose_leak_eval, "run_machine", lambda _cases: [])
        monkeypatch.setattr(qp.coach_prose_leak_eval, "summarize", lambda _outcomes: fake_report)
        result = qp._axis_coach_prose_leak()
        assert result.status == "gate_fail"

    def test_forces_flag_on_and_restores_previous_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, str | None] = {}

        def _fake_run_machine(_cases: object) -> list[object]:
            captured["flag_during_run"] = os.environ.get(qp._PROSE_FLAG_ENV)
            return []

        fake_report = ProseLeakReport(
            defect_total=1, leaked=0, clean_total=1, false_blocked=0, by_cell={}
        )
        monkeypatch.setattr(qp.coach_prose_leak_eval, "run_machine", _fake_run_machine)
        monkeypatch.setattr(qp.coach_prose_leak_eval, "summarize", lambda _outcomes: fake_report)
        monkeypatch.setenv(qp._PROSE_FLAG_ENV, "false")  # 이전 값(canary) — 원복 검증용

        qp._axis_coach_prose_leak()

        assert captured["flag_during_run"] == "true"  # 측정 중엔 강제 ON
        assert os.environ.get(qp._PROSE_FLAG_ENV) == "false"  # 종료 후 원복


# ──────────────────────────────────────────────────────────────────────────
# 축 6 — content_provenance(저작권, ARCH-20)
# ──────────────────────────────────────────────────────────────────────────


class TestAxisContentProvenance:
    def test_ok_on_empty_corpus_root(self, tmp_path: Path) -> None:
        corpus_root = tmp_path / "corpus"
        corpus_root.mkdir()
        result = qp._axis_content_provenance(corpus_root)
        assert result.status == "ok"
        assert result.detail == {"exit_code": 0}

    def test_gate_fail_on_missing_sidecar(self, tmp_path: Path) -> None:
        corpus_root = tmp_path / "corpus"
        (corpus_root / "some_bank").mkdir(parents=True)
        result = qp._axis_content_provenance(corpus_root)
        assert result.status == "gate_fail"
        assert result.detail["exit_code"] == 1


# ──────────────────────────────────────────────────────────────────────────
# 축 7 — defect_injection_demotion(결함주입 강등전) — 시더/실행/집계 monkeypatch
# ──────────────────────────────────────────────────────────────────────────


class TestAxisDefectInjectionDemotion:
    def test_ok_when_thresholds_met(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = DetectionReport(
            per_class={},
            defective_detected=100,
            defective_total=100,
            false_alarm=0,
            clean_total=100,
        )
        monkeypatch.setattr(qp, "build_defect_seeded_set", lambda **_kwargs: [])
        monkeypatch.setattr(
            qp.defect_detection_eval, "_run_machine", lambda _items, with_auditor=False: []
        )
        monkeypatch.setattr(qp.defect_detection_eval, "summarize", lambda _outcomes: fake_report)
        result = qp._axis_defect_injection_demotion()
        assert result.status == "ok"

    def test_gate_fail_on_low_detection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = DetectionReport(
            per_class={}, defective_detected=50, defective_total=100, false_alarm=0, clean_total=100
        )
        monkeypatch.setattr(qp, "build_defect_seeded_set", lambda **_kwargs: [])
        monkeypatch.setattr(
            qp.defect_detection_eval, "_run_machine", lambda _items, with_auditor=False: []
        )
        monkeypatch.setattr(qp.defect_detection_eval, "summarize", lambda _outcomes: fake_report)
        result = qp._axis_defect_injection_demotion()
        assert result.status == "gate_fail"

    def test_gate_fail_on_high_false_alarm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = DetectionReport(
            per_class={},
            defective_detected=100,
            defective_total=100,
            false_alarm=50,
            clean_total=100,
        )
        monkeypatch.setattr(qp, "build_defect_seeded_set", lambda **_kwargs: [])
        monkeypatch.setattr(
            qp.defect_detection_eval, "_run_machine", lambda _items, with_auditor=False: []
        )
        monkeypatch.setattr(qp.defect_detection_eval, "summarize", lambda _outcomes: fake_report)
        result = qp._axis_defect_injection_demotion()
        assert result.status == "gate_fail"


# ──────────────────────────────────────────────────────────────────────────
# 축 8 — banned_words_pii(학생 대면 산문 금칙어·PII, ARCH-24) — run() monkeypatch
# ──────────────────────────────────────────────────────────────────────────


class TestAxisBannedWordsPii:
    def test_ok_when_no_hits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = BannedWordsPiiReport(
            fields_scanned=7780,
            banned_word_hits=0,
            pii_third_party_hits=0,
            pii_self_reflection_hits=0,
            parse_error_count=0,
            by_corpus={},
        )
        monkeypatch.setattr(qp.banned_words_pii_eval, "run", lambda _root: fake_report)
        result = qp._axis_banned_words_pii(Path("/unused"))
        assert result.status == "ok"
        assert result.detail["fields_scanned"] == 7780
        assert result.detail["banned_word_hits"] == 0

    def test_gate_fail_on_high_banned_word_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 소표본(n=10) 중 5건 위반 — Wilson 상한이 임계(모듈 상수)를 크게 초과.
        fake_report = BannedWordsPiiReport(
            fields_scanned=10,
            banned_word_hits=5,
            pii_third_party_hits=0,
            pii_self_reflection_hits=0,
            parse_error_count=0,
            by_corpus={},
        )
        monkeypatch.setattr(qp.banned_words_pii_eval, "run", lambda _root: fake_report)
        result = qp._axis_banned_words_pii(Path("/unused"))
        assert result.status == "gate_fail"

    def test_gate_fail_counts_third_party_pii_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_report = BannedWordsPiiReport(
            fields_scanned=10,
            banned_word_hits=0,
            pii_third_party_hits=5,
            pii_self_reflection_hits=0,
            parse_error_count=0,
            by_corpus={},
        )
        monkeypatch.setattr(qp.banned_words_pii_eval, "run", lambda _root: fake_report)
        result = qp._axis_banned_words_pii(Path("/unused"))
        assert result.status == "gate_fail"


# ──────────────────────────────────────────────────────────────────────────
# 축 9 — defect_report_intake(RPT-01 학생 결함 신고 채널 수집 현황) — 가짜 세션 팩토리 주입
# ──────────────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeAsyncSession:
    """`async with sessionmaker() as session:` 표면만 모사 — execute/rollback만 필요."""

    def __init__(self, *, count: int | None = None, execute_error: Exception | None = None) -> None:
        self._count = count
        self._execute_error = execute_error
        self.rolled_back = False

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, _stmt: Any) -> _FakeResult:
        if self._execute_error is not None:
            raise self._execute_error
        assert self._count is not None
        return _FakeResult(self._count)

    async def rollback(self) -> None:
        self.rolled_back = True


class _FakeSessionmaker:
    def __init__(self, session: _FakeAsyncSession) -> None:
        self._session = session

    def __call__(self) -> _FakeAsyncSession:
        return self._session


class _FakeOrigError(Exception):
    """asyncpg 원 예외 모사 — `sqlstate` 속성만 필요(qa_pipeline이 이걸로 판별)."""

    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        super().__init__(f"synthetic pg error {sqlstate}")


def _undefined_table_error() -> ProgrammingError:
    return ProgrammingError("SELECT count(*) FROM defect_report", {}, _FakeOrigError("42P01"))


class TestAxisDefectReportIntake:
    """ "미배선"(no_snapshot·table_exists=False)·"DB 도달 불가"(no_snapshot·table_exists=None)·
    "0건 접수"(ok)·"그 외 오류"(error 전파) — 3중 회계 + error 격리 변별력 재현."""

    def test_undefined_table_reports_no_snapshot_not_ok(self) -> None:
        """테이블 자체가 없음(마이그레이션 미적용) — 이중 회계의 "미배선" 값."""
        session = _FakeAsyncSession(execute_error=_undefined_table_error())
        maker = _FakeSessionmaker(session)
        result = qp._axis_defect_report_intake(maker)
        assert result.status == "no_snapshot"
        assert result.detail["table_exists"] is False
        assert session.rolled_back is True

    def test_zero_rows_reports_ok_with_count_zero_not_no_snapshot(self) -> None:
        """테이블은 있는데 0건 접수 — 이중 회계의 "0건 접수" 값(`no_snapshot`과 다른 값)."""
        session = _FakeAsyncSession(count=0)
        maker = _FakeSessionmaker(session)
        result = qp._axis_defect_report_intake(maker)
        assert result.status == "ok"
        assert result.detail == {"table_exists": True, "count": 0}

    def test_no_snapshot_and_ok_zero_are_distinguishable(self) -> None:
        """acceptance③ 핵심 단언 — 두 상태가 *다른 값*을 낸다(같으면 검증 실패)."""
        no_snapshot = qp._axis_defect_report_intake(
            _FakeSessionmaker(_FakeAsyncSession(execute_error=_undefined_table_error()))
        )
        ok_zero = qp._axis_defect_report_intake(_FakeSessionmaker(_FakeAsyncSession(count=0)))
        assert no_snapshot.status != ok_zero.status
        assert no_snapshot.to_json() != ok_zero.to_json()

    def test_nonzero_count_reports_ok_with_that_count(self) -> None:
        session = _FakeAsyncSession(count=7)
        maker = _FakeSessionmaker(session)
        result = qp._axis_defect_report_intake(maker)
        assert result.status == "ok"
        assert result.detail == {"table_exists": True, "count": 7}

    def test_other_programming_error_is_not_swallowed_as_no_snapshot(self) -> None:
        """undefined_table이 *아닌* ProgrammingError는 no_snapshot으로 흡수하지 않고 올린다
        (`_run_axis_safely`가 잡아 "error"로 격리 — 세 번째 구분값)."""
        other_error = ProgrammingError("SELECT 1", {}, _FakeOrigError("42601"))  # syntax_error
        session = _FakeAsyncSession(execute_error=other_error)
        maker = _FakeSessionmaker(session)
        with pytest.raises(ProgrammingError):
            qp._axis_defect_report_intake(maker)

    def test_connection_failure_reports_no_snapshot_not_error(self) -> None:
        """DB 도달 불가(연결 실패) — CI data-pipeline 잡처럼 Postgres 자체가 없는 정당한
        환경 제약이지 결함이 아니다(ARCH-23 r3 보강 (a)안) — no_snapshot(집계 제외)으로
        강등하되, "테이블 없음"(table_exists=False)과는 table_exists=None(모른다)으로
        계속 구분한다(3상태를 truthiness로 접지 않는다)."""
        conn_error = OperationalError("SELECT 1", {}, _FakeOrigError("08006"))
        session = _FakeAsyncSession(execute_error=conn_error)
        maker = _FakeSessionmaker(session)
        result = qp._axis_defect_report_intake(maker)
        assert result.status == "no_snapshot"
        assert result.measured is True
        assert result.detail["table_exists"] is None
        assert result.detail["db_reachable"] is False

    def test_real_connection_refused_error_reports_no_snapshot_not_error(self) -> None:
        """실측 회귀 — 실제 asyncpg 커넥션 풀 체크아웃 실패는 `sqlalchemy.exc.
        OperationalError`가 아니라 **래핑되지 않은** `ConnectionRefusedError`(`OSError`
        하위)로 그대로 올라온다(SQLAlchemy 2.0.52 + asyncpg 실측 확인 — Postgres 없는
        이 환경에서 `python -m whymath_backend.harness.qa_pipeline`을 실제로 돌려 발견).
        `OperationalError`만 잡는 최초 구현은 이 경로를 못 잡아 `_run_axis_safely`의 일반
        핸들러로 새어나가 "error"가 됐고, 그 상태로 continue-on-error를 제거했다면 CI가
        상시 red가 됐을 것이다(CLAUDE.md "외부 SDK 표면을 시임 테스트만으로 정합 선언
        금지" — 가짜 `OperationalError` 픽스처만으로는 이 결함을 잡지 못했다)."""
        conn_error = ConnectionRefusedError(111, "Connect call failed ('127.0.0.1', 5432)")
        session = _FakeAsyncSession(execute_error=conn_error)
        maker = _FakeSessionmaker(session)
        result = qp._axis_defect_report_intake(maker)
        assert result.status == "no_snapshot"
        assert result.measured is True
        assert result.detail["table_exists"] is None
        assert result.detail["db_reachable"] is False

    def test_table_missing_and_db_unreachable_no_snapshot_are_distinguishable(self) -> None:
        """3중 회계 핵심 단언 — "테이블 없음"과 "DB 도달 불가"가 둘 다 no_snapshot이어도
        *다른 값*을 낸다(같으면 어느 사태인지 구분 불가 — 변별력 위장)."""
        table_missing = qp._axis_defect_report_intake(
            _FakeSessionmaker(_FakeAsyncSession(execute_error=_undefined_table_error()))
        )
        conn_error = OperationalError("SELECT 1", {}, _FakeOrigError("08006"))
        db_unreachable = qp._axis_defect_report_intake(
            _FakeSessionmaker(_FakeAsyncSession(execute_error=conn_error))
        )
        assert table_missing.status == db_unreachable.status == "no_snapshot"
        assert table_missing.to_json() != db_unreachable.to_json()
        assert table_missing.detail["table_exists"] is False
        assert db_unreachable.detail["table_exists"] is None


# ──────────────────────────────────────────────────────────────────────────
# 예외 격리(_run_axis_safely) — 침묵 실패 금지 회귀
# ──────────────────────────────────────────────────────────────────────────


class TestRunAxisSafely:
    def test_isolates_exception_and_reports_type_name(self) -> None:
        def _boom() -> qp.AxisResult:
            raise ValueError("합성 실패")

        result = qp._run_axis_safely(_boom, axis_name="synthetic_axis")
        assert result.measured is False
        assert result.status == "error"
        assert result.detail == {"error_type": "ValueError"}

    def test_passthrough_on_success(self) -> None:
        expected = qp.AxisResult(measured=True, status="ok", detail={"k": 1})
        result = qp._run_axis_safely(lambda: expected, axis_name="synthetic_axis")
        assert result is expected


# ──────────────────────────────────────────────────────────────────────────
# 집계(_aggregate_overall) — 순수함수 단위테스트(축 실행과 분리)
# ──────────────────────────────────────────────────────────────────────────


class TestAggregateOverall:
    def test_all_ok_passes(self) -> None:
        axes = {
            "a": qp.AxisResult(measured=True, status="ok", detail={}),
            "b": qp.AxisResult(measured=True, status="ok", detail={}),
        }
        overall = qp._aggregate_overall(axes)
        assert overall.passed is True
        assert overall.failing_axes == []

    def test_no_snapshot_does_not_fail_overall(self) -> None:
        axes = {
            "corpus_audit": qp.AxisResult(measured=True, status="no_snapshot", detail={}),
            "other": qp.AxisResult(measured=True, status="ok", detail={}),
        }
        overall = qp._aggregate_overall(axes)
        assert overall.passed is True
        assert overall.failing_axes == []

    def test_gate_fail_fails_overall(self) -> None:
        axes = {
            "a": qp.AxisResult(measured=True, status="gate_fail", detail={}),
            "b": qp.AxisResult(measured=True, status="ok", detail={}),
        }
        overall = qp._aggregate_overall(axes)
        assert overall.passed is False
        assert overall.failing_axes == ["a"]

    def test_error_fails_overall(self) -> None:
        axes = {
            "a": qp.AxisResult(measured=False, status="error", detail={"error_type": "ValueError"}),
            "b": qp.AxisResult(measured=True, status="ok", detail={}),
        }
        overall = qp._aggregate_overall(axes)
        assert overall.passed is False
        assert overall.failing_axes == ["a"]

    def test_multiple_failing_axes_sorted(self) -> None:
        axes = {
            "z_axis": qp.AxisResult(measured=True, status="gate_fail", detail={}),
            "a_axis": qp.AxisResult(measured=True, status="error", detail={"error_type": "X"}),
        }
        overall = qp._aggregate_overall(axes)
        assert overall.passed is False
        assert overall.failing_axes == ["a_axis", "z_axis"]  # 정렬됨


# ──────────────────────────────────────────────────────────────────────────
# build_report — 전 축 조립 와이어링(무거운 3축은 monkeypatch로 격리해 경량 유지)
# ──────────────────────────────────────────────────────────────────────────


def test_build_report_assembles_axes_and_isolates_one_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _ok(*_args: object, **_kwargs: object) -> qp.AxisResult:
        return qp.AxisResult(measured=True, status="ok", detail={})

    def _boom() -> qp.AxisResult:
        raise RuntimeError("합성 실패")

    monkeypatch.setattr(
        qp,
        "_axis_corpus_audit",
        lambda _repo_root: qp.AxisResult(
            measured=True, status="no_snapshot", detail={"snapshot_count": 0}
        ),
    )
    monkeypatch.setattr(qp, "_axis_equivalence_canonicalize", _ok)
    monkeypatch.setattr(qp, "_axis_concept_graph_reachability", _ok)
    monkeypatch.setattr(qp, "_axis_misconception_crosslink_demotion", _ok)
    monkeypatch.setattr(qp, "_axis_coach_prose_leak", _boom)
    monkeypatch.setattr(qp, "_axis_content_provenance", _ok)
    monkeypatch.setattr(qp, "_axis_defect_injection_demotion", _ok)
    monkeypatch.setattr(qp, "_axis_banned_words_pii", _ok)
    monkeypatch.setattr(qp, "_axis_defect_report_intake", _ok)

    report = qp.build_report(tmp_path, repo_root=tmp_path)

    assert report["corpus_root"] == str(tmp_path)
    assert set(report["axes"].keys()) == {
        "corpus_audit",
        "equivalence_canonicalize",
        "concept_graph_reachability",
        "misconception_crosslink_demotion",
        "coach_prose_leak",
        "content_provenance",
        "defect_injection_demotion",
        "banned_words_pii",
        "defect_report_intake",
    }
    assert report["axes"]["corpus_audit"]["status"] == "no_snapshot"
    assert report["axes"]["coach_prose_leak"]["status"] == "error"
    assert report["axes"]["coach_prose_leak"]["detail"]["error_type"] == "RuntimeError"
    assert report["axes"]["equivalence_canonicalize"]["status"] == "ok"
    assert report["axes"]["banned_words_pii"]["status"] == "ok"
    assert report["overall"]["pass"] is False
    assert report["overall"]["failing_axes"] == ["coach_prose_leak"]
    assert {a["name"] for a in report["not_measured_axes"]} == {
        "ui_golden",
        "statistical_outlier",
        "performance",
    }
    assert all(a["reason"] for a in report["not_measured_axes"])  # 전부 사유 명시(침묵 통과 금지)


def test_build_report_all_ok_passes_overall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _ok(*_args: object, **_kwargs: object) -> qp.AxisResult:
        return qp.AxisResult(measured=True, status="ok", detail={})

    for name in (
        "_axis_corpus_audit",
        "_axis_equivalence_canonicalize",
        "_axis_concept_graph_reachability",
        "_axis_misconception_crosslink_demotion",
        "_axis_coach_prose_leak",
        "_axis_content_provenance",
        "_axis_defect_injection_demotion",
        "_axis_banned_words_pii",
        "_axis_defect_report_intake",
    ):
        monkeypatch.setattr(qp, name, _ok)

    report = qp.build_report(tmp_path, repo_root=tmp_path)
    assert report["overall"] == {"pass": True, "failing_axes": []}


# ──────────────────────────────────────────────────────────────────────────
# CLI 통합 — 실제로 main([])을 끝까지 돌린다(느려도 필수 — acceptance).
# ──────────────────────────────────────────────────────────────────────────


def test_cli_main_runs_end_to_end_and_writes_valid_json(tmp_path: Path) -> None:
    json_path = tmp_path / "qa_report.json"
    rc = qp.main(["--json", str(json_path)])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"corpus_root", "axes", "not_measured_axes", "overall"}
    assert set(payload["axes"].keys()) == {
        "corpus_audit",
        "equivalence_canonicalize",
        "concept_graph_reachability",
        "misconception_crosslink_demotion",
        "coach_prose_leak",
        "content_provenance",
        "defect_injection_demotion",
        "banned_words_pii",
        "defect_report_intake",
    }
    # 미실행(no code path) 없이 전 축이 measured 또는 명시적 error로 보고됐는지 확인.
    for axis in payload["axes"].values():
        assert axis["status"] in ("ok", "no_snapshot", "gate_fail", "error")
    assert len(payload["not_measured_axes"]) == 3

    # exit code는 overall.pass와 정확히 일치해야 한다(정직 회계).
    assert rc == (0 if payload["overall"]["pass"] else 1)
