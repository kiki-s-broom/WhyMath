"""crosswalk 검수 큐 기계 트리아지 테스트 — 4버킷 분류·거부 집합 정합·봉인·advisory(hermetic).

순수 분류(합성 큐)와 커밋 큐 e2e(버킷 카운트 동결)를 봉인한다. 핵심 불변식: ① auto_reject 버킷은
`crosslink_machine_reject`와 *같은 집합*(단일 정본) ② 기계는 어떤 후보도 승인 표시하지 않는다
③ 큐를 읽기만 한다(전행 pending 무손상) ④ corroborated는 직접매핑·conf 순 우선 정렬.
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.l4.misconception.crosslink_machine_reject import run as reject_run
from whymath_backend.l4.misconception.crosslink_triage import (
    _load_mid_texts,
    format_worksheet,
    triage_candidates,
)
from whymath_backend.l4.misconception.crosslink_triage import (
    run as triage_run,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_KEBAB_STANDARDS = {
    "opposite-root-selected": frozenset({"[10공수1-02-02]"}),
    "extremum-max-min-confused": frozenset({"[12미적Ⅰ-02-07]"}),
}
_KEBAB_COUNTS = {"opposite-root-selected": 130, "extremum-max-min-confused": 3}
_MID_STANDARDS: dict[str, str | None] = {
    "M0862": "[10공수1-02-02]",  # agree(opposite-root)
    "M0900": "[12미적Ⅰ-02-07]",  # cross for opposite-root(disagree·well-evidenced)
    "M0901": "[9수02-19]",  # cross for extremum(disagree·thin evidence)
    "M0902": None,  # no standard → no_signal
}


def _queue(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"review_queue": rows}


def _row(kebab: str, mis: str, status: str = "pending") -> dict[str, object]:
    return {
        "kebab_id": kebab,
        "mis_id": mis,
        "link_type": "직접매핑",
        "confidence": 0.9,
        "rationale": "테스트",
        "status": status,
    }


class TestTriageCandidates:
    def test_four_buckets_classified(self) -> None:
        q = _queue(
            [
                _row("opposite-root-selected", "M0900"),  # disagree·증거 130 → auto_reject
                _row("opposite-root-selected", "M0862"),  # agree → corroborated
                _row("extremum-max-min-confused", "M0901"),  # disagree·증거 3 → thin_disagree
                _row("opposite-root-selected", "M0902"),  # M표준 없음 → no_signal
            ]
        )
        report = triage_candidates(
            queue=q,
            kebab_standards=_KEBAB_STANDARDS,
            kebab_counts=_KEBAB_COUNTS,
            mid_standards=_MID_STANDARDS,
            evidence_floor=20,
        )
        buckets = {(c.kebab_id, c.mis_id): c.bucket for c in report.candidates}
        assert buckets[("opposite-root-selected", "M0900")] == "auto_reject"
        assert buckets[("opposite-root-selected", "M0862")] == "corroborated"
        assert buckets[("extremum-max-min-confused", "M0901")] == "thin_disagree"
        assert buckets[("opposite-root-selected", "M0902")] == "no_signal"
        assert report.counts == {
            "auto_reject": 1,
            "corroborated": 1,
            "thin_disagree": 1,
            "no_signal": 1,
        }

    def test_non_pending_rows_skipped(self) -> None:
        # 사람이 판정한 행(approved/rejected)은 트리아지 대상 아님(불변).
        q = _queue([_row("opposite-root-selected", "M0900", status="approved")])
        report = triage_candidates(
            queue=q,
            kebab_standards=_KEBAB_STANDARDS,
            kebab_counts=_KEBAB_COUNTS,
            mid_standards=_MID_STANDARDS,
            evidence_floor=20,
        )
        assert report.candidates == ()

    def test_no_approval_bucket_exists(self) -> None:
        # 봉인 — 어떤 후보도 승인 버킷에 담기지 않는다(기계 승인 0·초인간 검증 §3.3).
        q = _queue([_row("opposite-root-selected", "M0862")])
        report = triage_candidates(
            queue=q,
            kebab_standards=_KEBAB_STANDARDS,
            kebab_counts=_KEBAB_COUNTS,
            mid_standards=_MID_STANDARDS,
            evidence_floor=20,
        )
        assert all(
            c.bucket in ("auto_reject", "corroborated", "thin_disagree", "no_signal")
            for c in report.candidates
        )


class TestCommittedQueueEndToEnd:
    def _run(self) -> object:
        return triage_run(
            queue_path=_REPO_ROOT / "docs" / "data" / "misconception_crosslink_review_queue.json",
            corpora=sorted((_REPO_ROOT / "data" / "corpus").glob("problem_bank_*/problems.jsonl")),
            misconceptions=_REPO_ROOT
            / "data"
            / "corpus"
            / "misconceptions_v1"
            / "misconceptions.json",
            evidence_floor=20,
        )

    def test_committed_bucket_counts(self) -> None:
        # 커밋 큐 e2e — 843 트랜치5 6종 corroborated 추가(101→107)·no_signal 0·thin_disagree 0
        # (탐지 카탈로그 40 전수 등장·agree). MISC-21(앵커 A1·A2·A3 좌석 보강) 3종은 아직 문항
        # 코퍼스에 등장하지 않아(kebab 문항 미등장) no_signal 3건으로 정직 집계된다 — 기계가
        # agreement를 판정할 신호 자체가 없다는 뜻이지 오매핑 의심이 아니다(사람 검수 대상).
        report = self._run()
        assert report.counts == {  # type: ignore[attr-defined]
            "corroborated": 107,
            "no_signal": 3,
            "auto_reject": 4,
            "thin_disagree": 0,
        }

    def test_auto_reject_matches_machine_reject_tool(self) -> None:
        # 단일 정본 — 트리아지 auto_reject 집합 == crosslink_machine_reject 산출(불일치 금지).
        report = self._run()
        triage_rejects = {
            (c.kebab_id, c.mis_id)
            for c in report.bucket("auto_reject")  # type: ignore[attr-defined]
        }
        machine_rejects = {
            (r.kebab_id, r.mis_id)
            for r in reject_run(
                queue_path=_REPO_ROOT
                / "docs"
                / "data"
                / "misconception_crosslink_review_queue.json",
                corpora=sorted(
                    (_REPO_ROOT / "data" / "corpus").glob("problem_bank_*/problems.jsonl")
                ),
                misconceptions=_REPO_ROOT
                / "data"
                / "corpus"
                / "misconceptions_v1"
                / "misconceptions.json",
                evidence_floor=20,
            )
        }
        assert triage_rejects == machine_rejects

    def test_corroborated_sorted_direct_first(self) -> None:
        # 인간 우선 검토 정렬 — 직접매핑이 부분매핑/개념겹침보다 앞·conf 내림차순.
        report = self._run()
        corroborated = report.bucket("corroborated")  # type: ignore[attr-defined]
        ranks = ["직접매핑", "부분매핑", "개념겹침"]
        rank_seq = [ranks.index(c.link_type) for c in corroborated]
        assert rank_seq == sorted(rank_seq)  # 링크 유형 비내림차순

    def test_queue_unchanged_all_pending(self) -> None:
        # 봉인 준수 — 트리아지는 큐를 읽기만 한다(전행 pending 유지).
        q = json.loads(
            (_REPO_ROOT / "docs" / "data" / "misconception_crosslink_review_queue.json").read_text(
                encoding="utf-8"
            )
        )
        assert all(row["status"] == "pending" for row in q["review_queue"])


class TestWorksheet:
    def test_shows_both_statements_and_decision(self) -> None:
        # 워크시트는 두 서술(kebab↔M-id)을 대조하고 판정란을 낸다·기계 승인 없음.
        q = _queue([_row("opposite-root-selected", "M0862")])
        report = triage_candidates(
            queue=q,
            kebab_standards=_KEBAB_STANDARDS,
            kebab_counts=_KEBAB_COUNTS,
            mid_standards=_MID_STANDARDS,
            evidence_floor=20,
        )
        text = format_worksheet(
            report,
            kebab_statements={"opposite-root-selected": ("반대근 선택", "작은 근을 답한다")},
            mid_texts={"M0862": ("부호 반대 근", "큰 근 대신 작은 근")},
            bucket="corroborated",
        )
        assert "작은 근을 답한다" in text  # kebab 서술
        assert "부호 반대 근" in text  # M-id 서술
        assert "[ ] 승인" in text and "[ ] 반려" in text  # 판정란
        assert "기계 승인 0" in text  # 봉인 문구
        assert "opposite-root-selected → M0862" in text

    def test_load_mid_texts(self, tmp_path: Path) -> None:
        path = tmp_path / "mis.json"
        path.write_text(
            json.dumps(
                {
                    "misconceptions": [
                        {
                            "mis_id": "M0001",
                            "canonical_statement": "진술 A",
                            "student_wrong_thinking": "오사고 B",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        texts = _load_mid_texts(path)
        assert texts["M0001"] == ("진술 A", "오사고 B")
