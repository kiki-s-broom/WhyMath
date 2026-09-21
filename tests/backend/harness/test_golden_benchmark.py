"""골든 벤치마크 승격·동결 규약 — as-found fail-closed·회전·digest (EOS-60 acceptance ①③⑥).

정본: `harness/golden_benchmark.py`. 검증 축:
  - **as-found 무결성(⑥·fail-closed)** — rejected는 승격, approved는 ⓐ 스냅샷/ⓑ edit-aware
    verdict 없이는 **제외**. 제외분 건수가 리포트에 명시되는지까지 실측(조용한 포함 금지).
  - ⓑ 경로의 **시각 경계** — 어휘가 있어도 `--edit-aware-since` 없으면 승격 불가,
    경계 이전 검수분도 승격 불가(소급 재분류 금지·EOS-62 ④).
  - **회전(③)** — 같은 rotation 바이트 재현·다른 rotation 선택 재배열(변별력 양방향).
  - **동결(③)** — digest는 내용의 함수이며 손편집 변조는 로드 시 터진다.
  - **재채점 금지 원장** — 같은 digest·다른 리비전만 위반(같은 리비전 재실행은 허용).
  - **앵커 id 정합** — 1급 등록(`data/corpus/eos_anchor_set_v1/anchors.yaml`·EOS-56)과 기계 대조.
  - **CLI exit** — 승격 0건·입력 부재·파싱 실패 혼입은 전부 exit 1(통과 아님).

hermetic — tmp_path·픽스처만(파일 I/O 외 부작용 0·LLM/DB/네트워크 0).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from whymath_backend.harness.golden_benchmark import (
    ANCHOR_IDS,
    AnchorRow,
    AsFoundBasis,
    AsFoundRow,
    EvaluationRecord,
    GoldenItem,
    GoldenLabel,
    append_evaluation_ledger,
    compute_digest,
    edit_aware_verdict_available,
    find_rescore_violation,
    freeze_golden_set,
    load_evaluation_ledger,
    load_golden_set,
    main,
    parse_anchor_rows,
    parse_as_found_rows,
    promote_from_events,
    render_promotion_report,
    select_by_anchor,
    write_golden_set,
)
from whymath_backend.harness.review_timer import (
    append_event_jsonl,
    finish_review,
    start_review,
)
from whymath_backend.harness.reviewer_sample_package import rotation_key
from whymath_backend.l1.standards.anchor_registry import (
    SCOPE_DECEMBER_2026,
    SCOPE_DEFERRED_2027_01,
    load_anchor_registry,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import ReviewTimerEvent

_T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _finish(
    cu_slug: str,
    verdict: str,
    *,
    failure_code: GenerationFailureCode | None = None,
    at: datetime | None = None,
) -> ReviewTimerEvent:
    """종결 이벤트 1건 — 실 writer(`finish_review`)를 쓴다(계약 위반은 여기서 터진다)."""
    return finish_review(
        review_session_id=uuid.uuid4(),
        cu_slug=cu_slug,
        reviewer_id="kiki",
        verdict=verdict,  # type: ignore[arg-type]
        elapsed_ms=120_000,
        failure_code=failure_code,
        occurred_at=at or _T0,
    )


def _anchors(*pairs: tuple[str, str]) -> list[AnchorRow]:
    return [AnchorRow(cu_slug=slug, anchor_id=anchor) for slug, anchor in pairs]


# ──────────────────────────────────────────────────────────────────────────
# ⑥ as-found 라벨 무결성 — fail-closed
# ──────────────────────────────────────────────────────────────────────────
class TestAsFoundIntegrity:
    """승격 경로 3종과 그 부재 시 제외 — 골든의 존재 이유(FN 과소평가 방지)를 지킨다."""

    def test_rejected_promotes_as_defective_with_failure_code(self) -> None:
        events = [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-a", "A4")))

        assert report.promoted_count == 1
        item = report.promoted[0]
        assert item.label == GoldenLabel.DEFECTIVE
        assert item.failure_code == GenerationFailureCode.F2
        assert item.as_found_basis == AsFoundBasis.REJECTED_FAILURE_CODE
        assert item.anchor_id == "A4"
        assert report.excluded_ambiguous_approved == 0

    def test_approved_is_excluded_without_snapshot_or_edit_aware_verdict(self) -> None:
        """손질 후 승인이 clean으로 섞이면 FN율이 과소평가된다 — 그래서 기본 제외다."""
        events = [_finish("cu-b", "approved")]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-b", "A4")))

        assert report.promoted_count == 0
        assert report.excluded_ambiguous_approved == 1

    def test_ambiguous_exclusion_is_stated_in_report(self) -> None:
        """제외는 조용히 하지 않는다 — 건수가 리포트 본문에 찍혀야 미측정이 보인다."""
        events = [_finish("cu-b", "approved"), _finish("cu-c", "approved")]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-b", "A4"), ("cu-c", "A4")))

        rendered = render_promotion_report(report)
        assert "모호 승인" in rendered
        assert "2건" in rendered

    def test_pre_review_snapshot_unlocks_approved_promotion(self) -> None:
        """ⓐ 검수 전 스냅샷이 있으면 그 라벨이 정답지다(clean·defective 양쪽)."""
        events = [_finish("cu-b", "approved"), _finish("cu-c", "approved")]
        as_found = [
            AsFoundRow(cu_slug="cu-b", label=GoldenLabel.CLEAN),
            AsFoundRow(
                cu_slug="cu-c",
                label=GoldenLabel.DEFECTIVE,
                failure_code=GenerationFailureCode.F3,
            ),
        ]
        report = promote_from_events(
            events,
            anchor_rows=_anchors(("cu-b", "A4"), ("cu-c", "A5")),
            as_found_rows=as_found,
        )

        by_slug = {item.cu_slug: item for item in report.promoted}
        assert by_slug["cu-b"].label == GoldenLabel.CLEAN
        assert by_slug["cu-b"].failure_code is None
        assert by_slug["cu-c"].label == GoldenLabel.DEFECTIVE
        assert by_slug["cu-c"].failure_code == GenerationFailureCode.F3
        assert all(i.as_found_basis == AsFoundBasis.PRE_REVIEW_SNAPSHOT for i in report.promoted)
        assert report.excluded_ambiguous_approved == 0

    def test_edit_aware_since_alone_does_not_unlock_when_vocabulary_absent(
        self, monkeypatch
    ) -> None:
        """ⓑ는 어휘 실측에 걸린다 — 어휘가 없으면 시각만 줘도 여전히 제외.

        EOS-62 착지로 실 어휘는 3값이 됐다. 그래도 이 계약을 **지우거나 skip으로 두지 않는다**
        — 프로브가 False를 낼 때(어휘 롤백·하류 배포 지연) fail-closed가 유지되는지가 이
        규약의 안전 속성이고, skip은 그것을 검사하지 않으면서 통과처럼 보인다. 그래서 프로브를
        눌러 그 상태를 *만들어* 검사한다.
        """
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: False,
        )
        events = [_finish("cu-b", "approved")]
        report = promote_from_events(
            events,
            anchor_rows=_anchors(("cu-b", "A4")),
            edit_aware_since=_T0 - timedelta(days=1),
        )

        assert report.promoted_count == 0
        assert report.excluded_ambiguous_approved == 1
        assert report.edit_aware_available is False

    def test_edit_aware_path_requires_explicit_since_boundary(self, monkeypatch) -> None:
        """어휘가 있어도 경계 시각이 없으면 전부 제외 — 과거 approved의 조용한 혼입 차단."""
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: True,
        )
        events = [_finish("cu-b", "approved")]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-b", "A4")))

        assert report.promoted_count == 0
        assert report.excluded_ambiguous_approved == 1

    def test_edit_aware_path_excludes_reviews_before_boundary(self, monkeypatch) -> None:
        """소급 재분류 금지(EOS-62 ④) — 계약 착지 *이전* 검수분은 어휘가 있어도 영구 모호."""
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: True,
        )
        boundary = _T0
        events = [
            _finish("cu-old", "approved", at=boundary - timedelta(days=1)),
            _finish("cu-new", "approved", at=boundary + timedelta(days=1)),
        ]
        report = promote_from_events(
            events,
            anchor_rows=_anchors(("cu-old", "A4"), ("cu-new", "A4")),
            edit_aware_since=boundary,
        )

        assert [i.cu_slug for i in report.promoted] == ["cu-new"]
        assert report.promoted[0].label == GoldenLabel.CLEAN
        assert report.promoted[0].as_found_basis == AsFoundBasis.EDIT_AWARE_VERDICT
        assert report.excluded_ambiguous_approved == 1

    def test_unmapped_anchor_is_excluded_not_silently_bucketed(self) -> None:
        """앵커 미매핑은 승격 불가 — 앵커별 쿼터·앵커별 FN 보고가 성립하지 않기 때문."""
        events = [_finish("cu-x", "rejected", failure_code=GenerationFailureCode.F1)]
        report = promote_from_events(events, anchor_rows=[])

        assert report.promoted_count == 0
        assert report.excluded_unmapped_anchor == 1

    def test_only_finished_events_become_labels(self) -> None:
        """started/aborted는 판정이 없다 — 라벨이 되지 못하고 분모도 오염시키지 않는다."""
        started = start_review(cu_slug="cu-a", reviewer_id="kiki")
        finished = _finish("cu-a", "rejected", failure_code=GenerationFailureCode.F1)
        report = promote_from_events([started, finished], anchor_rows=_anchors(("cu-a", "A4")))

        assert report.total_events == 2
        assert report.finished_events == 1
        assert report.promoted_count == 1

    def test_duplicate_cu_keeps_latest_verdict_only(self) -> None:
        """한 CU는 정답지에서 한 표다 — 중복 판정은 최신 1건만 승격하고 건수로 보고."""
        events = [
            _finish("cu-a", "rejected", failure_code=GenerationFailureCode.F1, at=_T0),
            _finish(
                "cu-a",
                "rejected",
                failure_code=GenerationFailureCode.F8,
                at=_T0 + timedelta(hours=1),
            ),
        ]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-a", "A4")))

        assert report.promoted_count == 1
        assert report.promoted[0].failure_code == GenerationFailureCode.F8
        assert report.excluded_duplicate_cu == 1


# ──────────────────────────────────────────────────────────────────────────
# ③ 과적합 방지 — 회전·동결·재채점 금지
# ──────────────────────────────────────────────────────────────────────────
def _item(slug: str, anchor: str = "A4", label: GoldenLabel = GoldenLabel.DEFECTIVE) -> GoldenItem:
    return GoldenItem(
        cu_slug=slug,
        anchor_id=anchor,
        label=label,
        failure_code=GenerationFailureCode.F2 if label == GoldenLabel.DEFECTIVE else None,
        as_found_basis=AsFoundBasis.REJECTED_FAILURE_CODE,
    )


class TestRotationAndFreeze:
    """S2-11 재추출·동결 기록 — "교정 후 같은 표본 재채점 금지"의 골든 적용."""

    def test_same_rotation_is_byte_reproducible(self) -> None:
        items = [_item(f"cu-{i:03d}") for i in range(20)]
        prior = {"cu-000"}
        first = select_by_anchor(items, quota=5, rotation=3, exclude=prior)
        second = select_by_anchor(items, quota=5, rotation=3, exclude=prior)

        assert [i.cu_slug for i in first] == [i.cu_slug for i in second]

    def test_rotation_without_exclusion_is_refused(self) -> None:
        """#928 리뷰 P1 — 회전만으로는 신규 표본이 보장되지 않는다(fail-closed).

        후보가 쿼터 이하면(우리 목표 규모 30~35 = 기본 쿼터 35의 바로 그 구간) 회전은 순서만
        바꾸고 전건이 선택돼 **같은 셋·같은 digest**가 나온다. 그러면 교정 후 재판정이 원장에
        영구 차단된다 — 규약이 스스로를 막는 상태. 그래서 제외 집합을 요구한다.
        """
        with pytest.raises(ValueError, match="제외 집합"):
            select_by_anchor([_item("cu-a")], quota=35, rotation=1)

    def test_rotation_alone_would_have_produced_the_same_set(self) -> None:
        """결함의 실재 증거 — 제외가 없으면 회전이 무력하다는 사실 자체를 동결한다."""
        items = [_item(f"cu-{i:03d}") for i in range(33)]  # 30~35 목표 구간
        rot0 = select_by_anchor(items, quota=35, rotation=0)
        # 같은 후보를 회전만 바꿔 뽑으면(제외를 우회해 직접 정렬) 전건이 그대로 선택된다.
        reordered = sorted(items, key=lambda i: rotation_key(i.cu_slug, 1))[:35]
        assert {i.cu_slug for i in reordered} == {i.cu_slug for i in rot0}
        assert compute_digest(rot0) == compute_digest(tuple(reordered))

    def test_exclusion_produces_a_disjoint_sample(self) -> None:
        """변별력 양방향 — 제외를 주면 실제로 겹치지 않는 신규 표본이 나온다."""
        first_pool = [_item(f"cu-{i:03d}") for i in range(35)]
        rot0 = select_by_anchor(first_pool, quota=35, rotation=0)
        grown = first_pool + [_item(f"cu-{i:03d}") for i in range(35, 80)]

        rot1 = select_by_anchor(grown, quota=35, rotation=1, exclude={i.cu_slug for i in rot0})

        assert {i.cu_slug for i in rot1} & {i.cu_slug for i in rot0} == set()
        assert compute_digest(rot0) != compute_digest(rot1)

    def test_exhausted_pool_yields_empty_selection_not_reuse(self) -> None:
        """후보가 소진되면 이전 표본을 재사용하지 않고 **비운다** — 부족은 리포트가 드러낸다."""
        items = [_item(f"cu-{i:03d}") for i in range(33)]
        rot0 = select_by_anchor(items, quota=35, rotation=0)

        rot1 = select_by_anchor(items, quota=35, rotation=1, exclude={i.cu_slug for i in rot0})

        assert rot1 == ()

    def test_quota_applies_per_anchor(self) -> None:
        items = [_item(f"a4-{i}", "A4") for i in range(10)] + [
            _item(f"a5-{i}", "A5") for i in range(3)
        ]
        selected = select_by_anchor(items, quota=5)

        counts: dict[str, int] = {}
        for item in selected:
            counts[item.anchor_id] = counts.get(item.anchor_id, 0) + 1
        assert counts == {"A4": 5, "A5": 3}  # 못 채운 앵커는 있는 만큼(0 채움 금지)

    def test_report_exposes_quota_shortfall(self) -> None:
        events = [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F1)]
        report = promote_from_events(events, anchor_rows=_anchors(("cu-a", "A4")))

        rendered = render_promotion_report(report, quota=30)
        assert "쿼터(30) 미달" in rendered
        assert "A1: 0건" in rendered  # 표본 0인 앵커도 표에 남는다(침묵 금지)

    def test_freeze_records_version_rotation_and_digest(self) -> None:
        golden = freeze_golden_set(
            [_item("cu-a"), _item("cu-b")], golden_version="v1", rotation=2, frozen_at=_T0
        )

        assert golden.golden_version == "v1"
        assert golden.rotation == 2
        assert golden.frozen_at == _T0
        assert golden.digest == compute_digest(golden.items)
        assert [i.cu_slug for i in golden.items] == ["cu-a", "cu-b"]

    def test_digest_is_content_function_not_order_function(self) -> None:
        one = freeze_golden_set([_item("cu-a"), _item("cu-b")], golden_version="v1")
        two = freeze_golden_set([_item("cu-b"), _item("cu-a")], golden_version="v1")

        assert one.digest == two.digest

    def test_label_edit_changes_digest(self) -> None:
        """라벨을 바꾸면 다른 골든이다 — 같은 셋으로 위장한 재채점을 digest가 막는다."""
        base = freeze_golden_set([_item("cu-a")], golden_version="v1")
        edited = freeze_golden_set([_item("cu-a", label=GoldenLabel.CLEAN)], golden_version="v1")

        assert base.digest != edited.digest

    def test_digest_is_representation_independent(self) -> None:
        """같은 정답지는 enum 인스턴스를 들든 값 문자열을 들든 같은 digest다(EOS-75).

        검증 경유 항목은 `use_enum_values`로 `str`("F2")을, `model_construct`(검증 우회)
        항목은 enum 인스턴스를 든다. `str(enum)`이 repr을 내는 구현에서는 둘의 digest가
        갈라져 재채점 금지 원장이 같은 셋의 재실행을 "다른 골든"으로 통과시켰다.
        """
        validated = _item("cu-a")
        constructed = GoldenItem.model_construct(
            cu_slug="cu-a",
            subject_id=validated.subject_id,
            anchor_id="A4",
            label=GoldenLabel.DEFECTIVE,
            failure_code=GenerationFailureCode.F2,
            as_found_basis=AsFoundBasis.REJECTED_FAILURE_CODE,
        )
        assert isinstance(validated.failure_code, str)
        assert isinstance(constructed.failure_code, GenerationFailureCode)

        assert compute_digest([validated]) == compute_digest([constructed])

    def test_tampered_file_fails_to_load(self, tmp_path: Path) -> None:
        """손편집 변조는 무증상으로 통과하지 않는다(로드 시 validator가 터진다)."""
        path = tmp_path / "golden.json"
        write_golden_set(path, freeze_golden_set([_item("cu-a")], golden_version="v1"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["items"][0]["label"] = "clean"
        payload["items"][0]["failure_code"] = None
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with pytest.raises(ValueError, match="digest"):
            load_golden_set(path)

    def test_roundtrip_preserves_items(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.json"
        golden = freeze_golden_set([_item("cu-a"), _item("cu-b")], golden_version="v2", rotation=1)
        write_golden_set(path, golden)

        loaded = load_golden_set(path)
        assert loaded.digest == golden.digest
        assert loaded.rotation == 1
        assert [i.cu_slug for i in loaded.items] == ["cu-a", "cu-b"]


class TestEvaluationLedger:
    """재채점 금지의 집행 부품 — 같은 골든 × 다른 리비전만 위반이다."""

    def test_same_revision_rerun_is_not_a_violation(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        append_evaluation_ledger(
            path, EvaluationRecord(digest="d" * 64, engine_revision="abc123", evaluated_at=_T0)
        )
        records, errors = load_evaluation_ledger(path)

        assert errors == []
        assert find_rescore_violation(records, digest="d" * 64, engine_revision="abc123") is None

    def test_same_golden_different_revision_is_a_violation(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        append_evaluation_ledger(
            path, EvaluationRecord(digest="d" * 64, engine_revision="abc123", evaluated_at=_T0)
        )
        records, _ = load_evaluation_ledger(path)

        violation = find_rescore_violation(records, digest="d" * 64, engine_revision="def456")
        assert violation is not None
        assert violation.engine_revision == "abc123"

    def test_missing_ledger_is_empty_not_error(self, tmp_path: Path) -> None:
        records, errors = load_evaluation_ledger(tmp_path / "absent.jsonl")
        assert records == [] and errors == []

    def test_broken_ledger_line_preserves_reason(self, tmp_path: Path) -> None:
        """침묵 실패 금지 — 파싱 실패는 예외 타입명+줄 번호로 돌아온다."""
        path = tmp_path / "ledger.jsonl"
        path.write_text('{"digest": "x"}\n', encoding="utf-8")

        records, errors = load_evaluation_ledger(path)
        assert records == []
        assert len(errors) == 1 and "KeyError" in errors[0]


# ──────────────────────────────────────────────────────────────────────────
# 스키마·파서 계약
# ──────────────────────────────────────────────────────────────────────────
class TestSchemaContracts:
    def test_subject_id_defaults_to_math_and_is_settable(self) -> None:
        """Validation의 Math 비종속 좌석 — 처음부터 스키마에 있다(acceptance ⑤ 후단)."""
        assert _item("cu-a").subject_id == "math"
        physics = GoldenItem(
            cu_slug="cu-p",
            subject_id="physics",
            anchor_id="A4",
            label=GoldenLabel.CLEAN,
            as_found_basis=AsFoundBasis.PRE_REVIEW_SNAPSHOT,
        )
        assert physics.subject_id == "physics"

    def test_clean_label_rejects_failure_code(self) -> None:
        with pytest.raises(ValueError, match="clean"):
            GoldenItem(
                cu_slug="cu-a",
                anchor_id="A4",
                label=GoldenLabel.CLEAN,
                failure_code=GenerationFailureCode.F1,
                as_found_basis=AsFoundBasis.PRE_REVIEW_SNAPSHOT,
            )

    def test_unknown_anchor_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="앵커"):
            GoldenItem(
                cu_slug="cu-a",
                anchor_id="A9",
                label=GoldenLabel.CLEAN,
                as_found_basis=AsFoundBasis.PRE_REVIEW_SNAPSHOT,
            )

    def test_anchor_ids_match_frozen_registry(self) -> None:
        """앵커 id 정본은 **1급 등록**(`data/corpus/eos_anchor_set_v1/anchors.yaml`·EOS-56).

        등록은 8앵커 원안(대학 A7·A8 포함)을 그대로 들고 있고, G0 확정(검증설계서 §1-1)은
        **대학 2종을 2027-01로 이월**해 6앵커로 좁혔다. 그래서 "같다"가 아니라 "이월분을 뺀
        나머지와 같다"가 계약이다 — K-12 앵커가 늘거나 줄면 이 테스트가 깨져 골든 쿼터 축을
        함께 고치게 한다.

        이월 판정은 **등록의 `scope` 필드**로 한다(하드코딩 {A7, A8} 아님) — 이월이 데이터가
        아니면 2027-01에 A7·A8을 되살릴 때 이 테스트가 조용히 거짓말을 한다.
        """
        registry = load_anchor_registry()
        december = {a.id for a in registry.in_scope(SCOPE_DECEMBER_2026)}
        deferred = {a.id for a in registry.in_scope(SCOPE_DEFERRED_2027_01)}

        assert december == set(ANCHOR_IDS)
        assert deferred, "이월 앵커가 0건 — scope 축이 죽었는지 확인하라(상시 통과 위장 방지)"
        assert all("대학" in registry.by_id(a).title for a in deferred)

    def test_anchor_row_parser_rejects_vocabulary_outsiders(self) -> None:
        rows, errors = parse_anchor_rows(
            [
                {"cu_slug": "cu-a", "anchor_id": "A4"},
                {"slug": "cu-b", "anchor": "A9"},
                {"anchor_id": "A4"},
            ]
        )
        assert [r.cu_slug for r in rows] == ["cu-a"]
        assert len(errors) == 2

    def test_as_found_parser_preserves_failure_reasons(self) -> None:
        rows, errors = parse_as_found_rows(
            [
                {"cu_slug": "cu-a", "as_found_label": "clean"},
                {"cu_slug": "cu-b", "label": "sorta-ok"},
                {"cu_slug": "cu-c", "label": "defective", "failure_code": "F99"},
            ]
        )
        assert [r.cu_slug for r in rows] == ["cu-a"]
        assert len(errors) == 2
        assert all("ValueError" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────────
# CLI — 측정 실패 승격(④)
# ──────────────────────────────────────────────────────────────────────────
def _write_events(path: Path, events: list[ReviewTimerEvent]) -> None:
    for event in events:
        append_event_jsonl(path, event)


def _write_anchor_map(path: Path, pairs: list[tuple[str, str]]) -> None:
    path.write_text(
        "".join(
            json.dumps({"cu_slug": slug, "anchor_id": anchor}, ensure_ascii=False) + "\n"
            for slug, anchor in pairs
        ),
        encoding="utf-8",
    )


class TestCli:
    def test_promotes_and_freezes(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        out_path = tmp_path / "golden.json"
        _write_events(
            events_path,
            [
                _finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2),
                _finish("cu-b", "approved"),
            ],
        )
        _write_anchor_map(anchors_path, [("cu-a", "A4"), ("cu-b", "A4")])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--out",
                str(out_path),
                "--golden-version",
                "v1",
            ]
        )

        assert code == 0
        golden = load_golden_set(out_path)
        assert [i.cu_slug for i in golden.items] == ["cu-a"]  # approved는 fail-closed 제외

    def test_zero_promotion_is_measurement_failure(self, tmp_path: Path) -> None:
        """골든 0건은 '통과'가 아니다(acceptance ④) — 변별력 확인용 대칭 케이스."""
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(events_path, [_finish("cu-b", "approved")])
        _write_anchor_map(anchors_path, [("cu-b", "A4")])

        code = main(["--events", str(events_path), "--anchor-map", str(anchors_path)])
        assert code == 1

    def test_missing_input_is_measurement_failure(self, tmp_path: Path) -> None:
        code = main(
            [
                "--events",
                str(tmp_path / "absent.jsonl"),
                "--anchor-map",
                str(tmp_path / "absent2.jsonl"),
            ]
        )
        assert code == 1

    def test_parse_failure_blocks_freeze(self, tmp_path: Path) -> None:
        """부분 입력으로 동결 금지 — 깨진 행이 반려였다면 정답지에서 defective가 사라진다."""
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )
        with events_path.open("a", encoding="utf-8") as fp:
            fp.write("{깨진 줄\n")
        _write_anchor_map(anchors_path, [("cu-a", "A4")])

        code = main(["--events", str(events_path), "--anchor-map", str(anchors_path)])
        assert code == 1

    def test_report_is_written_when_requested(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        report_path = tmp_path / "report.md"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )
        _write_anchor_map(anchors_path, [("cu-a", "A4")])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--report",
                str(report_path),
            ]
        )

        assert code == 0
        body = report_path.read_text(encoding="utf-8")
        assert "골든 벤치마크 승격 리포트" in body
        assert "as-found 라벨 무결성" in body


class TestEditAwareProbe:
    """어휘 실측 프로브 자체 — 상류 schema와 이 규약의 결선이 살아 있는가."""

    def test_probe_reports_landed_vocabulary(self) -> None:
        """EOS-62 착지를 프로브가 *실측*으로 본다 — 이 파일을 고치지 않고도 경로 ⓑ가 열렸다.

        프로브가 상류 `ReviewVerdict`를 직접 읽지 않고 상수였다면, 어휘가 늘어도 하류는 계속
        fail-closed였을 것이다(선언과 실체 불일치). 그 결선이 실제로 작동했음을 고정한다.
        """
        assert edit_aware_verdict_available() is True

    def test_probe_tracks_the_upstream_literal_not_a_local_copy(self, monkeypatch) -> None:
        """변별력 — 상류 어휘가 좁아지면 프로브도 False로 따라 내려간다."""
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.ReviewVerdict",
            Literal["approved", "rejected"],
        )
        assert edit_aware_verdict_available() is False


class TestEditAwareVerdictPromotion:
    """EOS-62 어휘로 실제 승격되는가 — **실 writer**로 만든 이벤트를 태운다.

    이 클래스는 EOS-62 착지 *전*에 `model_construct`(검증 우회)로 선계약을 굳혔던 자리다.
    어휘가 착지한 지금은 우회할 이유가 없으므로 `finish_review`(실 writer)로 바꿨다 — 검증을
    우회한 채 남겨 두면 "스키마가 이 값을 실제로 받는가"를 영원히 검사하지 않으면서 통과하고,
    그것이 이 저장소가 반복해 겪은 '선언과 실체 불일치'다. 어휘 밖 값 케이스만 `model_construct`
    를 유지한다(정의상 schema가 거부하는 값이라 실 writer로 만들 수 없다).
    """

    def test_approved_with_edit_promotes_as_defective(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: True,
        )
        event = finish_review(
            review_session_id=uuid.uuid4(),
            cu_slug="cu-edited",
            reviewer_id="kiki",
            verdict="approved_with_edit",
            failure_code=GenerationFailureCode.F7,
            elapsed_ms=90_000,
            occurred_at=_T0,
        )
        report = promote_from_events(
            [event],
            anchor_rows=_anchors(("cu-edited", "A5")),
            edit_aware_since=_T0 - timedelta(days=1),
        )

        assert report.promoted_count == 1
        item = report.promoted[0]
        assert item.label == GoldenLabel.DEFECTIVE  # 손질했다 = as-found는 결함이었다
        assert item.failure_code == GenerationFailureCode.F7
        assert item.as_found_basis == AsFoundBasis.EDIT_AWARE_VERDICT

    def test_vocabulary_outsider_is_counted_separately(self, monkeypatch) -> None:
        """상류가 이 규약이 모르는 값을 추가하면 모호 승인이 아니라 '어휘 밖'으로 센다.

        `escalate`는 schema가 거부하는 값이라(폐쇄 3종) 실 writer로는 만들 수 없다 — 상류가
        *이 규약보다 먼저* 어휘를 넓힌 미래를 모사하려면 여기서만 검증을 우회한다.
        """
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: True,
        )
        event = ReviewTimerEvent.model_construct(
            event_id=uuid.uuid4(),
            review_session_id=uuid.uuid4(),
            cu_slug="cu-escalated",
            problem_id=None,
            reviewer_id="kiki",
            event_type="finished",
            verdict="escalate",
            failure_code=None,
            failure_note=None,
            elapsed_ms=None,
            occurred_at=_T0,
            recorded_at=None,
        )
        report = promote_from_events(
            [event],
            anchor_rows=_anchors(("cu-escalated", "A5")),
            edit_aware_since=_T0 - timedelta(days=1),
        )

        assert report.promoted_count == 0
        assert report.excluded_unknown_verdict == 1
        assert report.excluded_ambiguous_approved == 0


class TestCliUnlockPaths:
    """승격 경로 ⓐ·ⓑ의 CLI 배선 — 규약이 코드로만 있고 CLI에서 못 쓰면 집행이 아니다."""

    def test_as_found_labels_unlock_clean_promotion(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        as_found_path = tmp_path / "as_found.jsonl"
        out_path = tmp_path / "golden.json"
        _write_events(events_path, [_finish("cu-b", "approved")])
        _write_anchor_map(anchors_path, [("cu-b", "A4")])
        as_found_path.write_text(
            json.dumps({"cu_slug": "cu-b", "as_found_label": "clean"}) + "\n", encoding="utf-8"
        )

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--as-found-labels",
                str(as_found_path),
                "--out",
                str(out_path),
            ]
        )

        assert code == 0
        golden = load_golden_set(out_path)
        assert [i.label for i in golden.items] == [GoldenLabel.CLEAN.value]

    def test_missing_as_found_file_is_measurement_failure(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )
        _write_anchor_map(anchors_path, [("cu-a", "A4")])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--as-found-labels",
                str(tmp_path / "absent.jsonl"),
            ]
        )
        assert code == 1

    def test_missing_anchor_map_is_measurement_failure(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )

        code = main(["--events", str(events_path), "--anchor-map", str(tmp_path / "absent.jsonl")])
        assert code == 1

    def test_unparsable_edit_aware_since_is_measurement_failure(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )
        _write_anchor_map(anchors_path, [("cu-a", "A4")])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--edit-aware-since",
                "어제",
            ]
        )
        assert code == 1

    def test_edit_aware_since_warns_when_vocabulary_absent(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        """어휘가 없는데 경계만 준 상태를 조용히 넘기지 않는다(경로 ⓑ 미적용 자인).

        위 계약과 같은 이유로 skip이 아니라 프로브를 눌러 검사한다 — 이 자인 문구가 사라지면
        사용자는 `--edit-aware-since`가 먹은 줄 안다.
        """
        monkeypatch.setattr(
            "whymath_backend.harness.golden_benchmark.edit_aware_verdict_available",
            lambda: False,
        )
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(
            events_path, [_finish("cu-a", "rejected", failure_code=GenerationFailureCode.F2)]
        )
        _write_anchor_map(anchors_path, [("cu-a", "A4")])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--edit-aware-since",
                "2026-09-01T00:00:00+00:00",
            ]
        )

        assert code == 0
        assert "EOS-62 미착지" in capsys.readouterr().err


def test_quota_must_be_positive() -> None:
    """쿼터 0은 "아무것도 안 뽑음"을 조용히 정상 처리하게 만든다 — 계약으로 막는다."""
    with pytest.raises(ValueError, match="quota"):
        select_by_anchor([_item("cu-a")], quota=0)


class TestCliExclusionWiring:
    """`--exclude-golden` 배선 — 규약이 코어에만 있고 CLI에서 못 쓰면 집행이 아니다(#928 P1)."""

    def _fixture(self, tmp_path: Path, slugs: list[str]) -> tuple[Path, Path]:
        events_path = tmp_path / "events.jsonl"
        anchors_path = tmp_path / "anchors.jsonl"
        _write_events(
            events_path,
            [_finish(s, "rejected", failure_code=GenerationFailureCode.F2) for s in slugs],
        )
        _write_anchor_map(anchors_path, [(s, "A4") for s in slugs])
        return events_path, anchors_path

    def test_rotation_without_exclude_golden_is_measurement_failure(self, tmp_path: Path) -> None:
        events_path, anchors_path = self._fixture(tmp_path, ["cu-a", "cu-b"])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--rotation",
                "1",
            ]
        )
        assert code == 1

    def test_exclusion_yields_new_digest_on_grown_pool(self, tmp_path: Path) -> None:
        """교정 후 재판정의 정본 경로 — 후보가 늘어난 뒤 이전 셋을 제외하면 새 골든이 나온다."""
        first_events, first_anchors = self._fixture(tmp_path, ["cu-a", "cu-b"])
        v1 = tmp_path / "golden_v1.json"
        assert (
            main(
                [
                    "--events",
                    str(first_events),
                    "--anchor-map",
                    str(first_anchors),
                    "--out",
                    str(v1),
                ]
            )
            == 0
        )

        grown_events, grown_anchors = self._fixture(
            tmp_path / "round2", ["cu-a", "cu-b", "cu-c", "cu-d"]
        )
        v2 = tmp_path / "golden_v2.json"
        code = main(
            [
                "--events",
                str(grown_events),
                "--anchor-map",
                str(grown_anchors),
                "--rotation",
                "1",
                "--exclude-golden",
                str(v1),
                "--golden-version",
                "v2",
                "--out",
                str(v2),
            ]
        )

        assert code == 0
        first = load_golden_set(v1)
        second = load_golden_set(v2)
        assert {i.cu_slug for i in second.items} == {"cu-c", "cu-d"}  # 이전 표본 재사용 0
        assert first.digest != second.digest  # → 원장이 재채점으로 막지 않는다

    def test_exhausted_pool_reports_measurement_failure(self, tmp_path: Path) -> None:
        """후보가 전부 이전 골든이면 승격 0건 = 측정 실패 — 재사용으로 채우지 않는다."""
        events_path, anchors_path = self._fixture(tmp_path, ["cu-a", "cu-b"])
        v1 = tmp_path / "golden_v1.json"
        assert (
            main(
                [
                    "--events",
                    str(events_path),
                    "--anchor-map",
                    str(anchors_path),
                    "--out",
                    str(v1),
                ]
            )
            == 0
        )

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--rotation",
                "1",
                "--exclude-golden",
                str(v1),
            ]
        )
        assert code == 1

    def test_missing_exclude_file_is_measurement_failure(self, tmp_path: Path) -> None:
        events_path, anchors_path = self._fixture(tmp_path, ["cu-a"])

        code = main(
            [
                "--events",
                str(events_path),
                "--anchor-map",
                str(anchors_path),
                "--rotation",
                "1",
                "--exclude-golden",
                str(tmp_path / "absent.json"),
            ]
        )
        assert code == 1

    def test_report_states_exclusion_accounting(self, tmp_path: Path, capsys) -> None:
        """제외 집합이 없으면 '초판만 가능'하다는 사실을 리포트가 자인한다."""
        events_path, anchors_path = self._fixture(tmp_path, ["cu-a"])

        assert main(["--events", str(events_path), "--anchor-map", str(anchors_path)]) == 0
        out = capsys.readouterr().out
        assert "회전·재추출" in out
        assert "제외 집합 없음" in out
