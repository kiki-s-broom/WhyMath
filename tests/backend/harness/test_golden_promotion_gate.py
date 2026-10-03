"""[EOS-64 ③] 골든 승격 경로 게이트 — 경로 밖 승격이 실제로 exit 1인가.

이 파일이 붙드는 것
------------------
③의 요구는 "정본 경로(코퍼스 실재 → 사람 판정 → review_status 백필 각인 → Wilson 게이트)를
거친 승격만 허용하고, 경로 밖 승격은 exit 1"이다. 그러므로 여기서 확인해야 하는 것은
"통과 케이스가 통과한다"가 아니라 **경로의 각 단을 하나씩 빼면 실제로 거부되는가**다 —
성공 경로만 보는 테스트는 게이트가 사실 아무것도 안 막아도 초록이다(변별력 없는 검증 금지).

그래서 축마다 **음성 대조 1건**을 둔다: 코퍼스에 없음 / 사람 판정 없음 / 사람이 반려함 /
백필을 안 거침(손각인) / 감사 각인값과 코퍼스값 불일치 / 각인값이 approved가 아님. 그리고
**양성 대조**(전건 통과)를 함께 둬 무차별 거부가 아님을 보인다.

여기서 **픽스처가 현실과 어긋나지 않게** 지키는 것 (2026-09-01 codex P1)
--------------------------------------------------------------------
초판 픽스처는 검수 큐와 코퍼스에 **같은 slug를 인위적으로** 써 넣었다. 실제 파이프라인에서
그 상태는 만들어질 수 없다 — `problem_corpus_accumulate`는 수용분만 코퍼스에, 비수용분만
검수 큐에 넣으므로 두 집합은 정의상 서로소다(`test_needs_review_worklist.py`가 그 불변을
동결한다). 그 날조 때문에 "큐 멤버십을 요구하면 실제 산출물이 0건 통과"라는 P1이 가려졌다.
그래서 이 파일의 CLI 픽스처는 **큐와 코퍼스의 slug를 겹치지 않게** 만들고, 겹침(재제출 이력)은
`TestReviewQueueIsInformationOnly`가 *별도로* 다룬다 — 그 경우에도 차단되지 않아야 한다.

실제 파이프라인 산출물이 이 게이트를 통과하는가는 여기서 답할 수 없다(입력을 이 파일이
만들기 때문이다). 그 질문은 축적 CLI를 실제로 관통시키는
`tests/backend/harness/test_eos_anchor_e2e_a4.py::TestGoldenPromotionGateOnPipelineOutput`이
기계로 답한다.

법정·검수 절차의 기계 대체 금지 축은 세 가지로 동결한다:
  ⓐ 사람 판정 없는 후보는 통과가 아니라 `no_human_verdict` 거부다(미측정≠정상).
  ⓑ 사람 판정을 우회하는 CLI 플래그가 **없다**(`--force`·`--skip-review` 류 부재).
  ⓒ 이 CLI는 쓰기 경로가 없다 — 입력 파일이 실행 후 바이트 불변이다.

EOS-136에서 더한 축(각각 음성 대조로 동결):
  ⓓ ④단 분모는 **검수 배치 전체**다 — 제안에서 빠진 반려·손질 승인도 결함으로 센다. 제안만
    세던 초판은 통과 경로의 결함 수가 항상 0이라 ④단이 "승인 ≥ 133건" 표본 하한으로 퇴화했다.
  ⓔ 손질 승인(`approved_with_edit`)은 ②단 `human_verdict_needs_edit`다 — 지금 내용의 승인이 아니다.
  ⓕ 검수 도구 판정 파일을 감사로그 자리에 넣으면 입력 손상(exit 2) — ②·③단 이중 계상 차단
    (CLI 대조는 `test_review_status_verdict_bridge.py::TestReviewVerdictFileIsNotTheAudit`).

EOS-27에서 더한 축:
  ⓖ 승인 뒤 내용 편집은 `review_content_changed`, 판정에 지문이 없으면
    `review_fingerprint_unverifiable`이다 — 모름은 일치가 아니다(`TestContentFingerprintStage`).
    실 파이프라인 관통 음성 대조는 `test_eos_anchor_e2e_a4.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.golden_promotion_gate import (
    AS_FOUND_DEFECT_VERDICTS,
    HUMAN_REVIEW_NOTICE,
    PromotionGateReport,
    _human_verdicts,
    certifies_current_content,
    evaluate_promotion,
    latest_human_verdict_events,
    main,
    render_gate_report,
)
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.schema.review_timer import review_content_fingerprint

# 슬러그 200건짜리 배치 — Wilson 상한(기본 임계 0.02)을 통과할 만큼 큰 표본.
# 작은 배치가 통과 못 하는 것은 설계이므로(모듈 docstring), 양성 대조는 표본을 키워서 만든다.
_BATCH = tuple(f"wm-gen-a4-{i:04d}" for i in range(200))

# 검수 큐에만 있는 slug(= 비수용 후보) — 코퍼스·제안 어느 쪽과도 겹치지 않는다.
# 실 파이프라인의 서로소 구조를 픽스처가 그대로 재현하기 위한 것이다.
_QUEUE_ONLY = tuple(f"wm-gen-a4-rej-{i:02d}" for i in range(3))


def _eval(slugs: tuple[str, ...] = _BATCH, **overrides: object) -> PromotionGateReport:
    """전건 통과 상태를 기본값으로 두고, 인자로 축 하나씩만 깨뜨린다.

    기본값의 큐는 **제안과 겹치지 않는다** — 수용 문항이 큐에 없는 것이 정상이므로, 정상
    상태가 곧 "큐 멤버십 0"이어야 한다(그 상태에서 통과해야 게이트가 실물을 통과시킨다).
    """
    kwargs: dict[str, object] = {
        "queue_slugs": set(_QUEUE_ONLY),
        "human_verdicts": {slug: "approved" for slug in slugs},
        "backfilled_status": {slug: "approved" for slug in slugs},
        "corpus_review_status": {slug: "approved" for slug in slugs},
    }
    kwargs.update(overrides)
    return evaluate_promotion(list(slugs), **kwargs)  # type: ignore[arg-type]


class TestPathEnforcement:
    """정본 경로 4단 — 각 단을 빼면 그 단의 사유로 거부된다."""

    def test_positive_control_full_path_is_approved(self) -> None:
        """양성 대조 — 4단 전건 충족 + 충분한 표본이면 승격 허용(무차별 거부가 아니다).

        여기서 제안 slug는 검수 큐에 **하나도 없다** — 실 파이프라인의 정상 상태다.
        큐 멤버십을 차단 조건으로 걸면 이 양성 대조가 빨개진다(P1 회귀 감지 지점).
        """
        report = _eval()
        assert report.off_path == []
        assert report.wilson_passed is True
        assert report.approved is True

    @pytest.mark.parametrize(
        ("override", "expected_reason"),
        [
            ({"corpus_review_status": {}}, "not_in_corpus"),
            ({"human_verdicts": {}}, "no_human_verdict"),
            ({"backfilled_status": {}}, "review_status_not_backfilled"),
        ],
        ids=["코퍼스_부재", "사람판정_없음", "백필_미경유"],
    )
    def test_missing_stage_blocks_with_its_own_reason(
        self, override: dict[str, object], expected_reason: str
    ) -> None:
        """음성 대조 — 단 하나를 빼면 **그 단의 사유**로 전건 차단(뭉뚱그린 거부 금지)."""
        report = _eval(**override)
        assert len(report.off_path) == len(_BATCH)
        assert {v.blocked_reason for v in report.off_path} == {expected_reason}
        assert report.approved is False

    def test_hand_stamped_review_status_is_refused(self) -> None:
        """손각인 차단 — 코퍼스 값이 approved여도 백필 감사로그에 없으면 경로 밖이다.

        이 게이트의 존재 이유 그 자체다: 값만 보면 백필 CLI가 각인한 것과 사람이 JSONL을
        손으로 고친 것을 구분할 수 없고, `l6/_shared.is_review_cleared`는 그 둘을 똑같이
        통과시킨다.
        """
        report = _eval(backfilled_status={_BATCH[0]: "approved"})
        blocked = report.off_path
        assert {v.blocked_reason for v in blocked} == {"review_status_not_backfilled"}
        assert len(blocked) == len(_BATCH) - 1

    def test_pending_review_status_is_not_promotable(self) -> None:
        """각인값이 approved가 아니면 거부 — 판정 권위는 `is_review_status_cleared` 단일.

        감사값과 코퍼스값이 **일치하되 pending**인 상태다(불일치 축과 구분하기 위해 양쪽을
        같이 pending으로 둔다).
        """
        report = _eval(
            backfilled_status={slug: "pending" for slug in _BATCH},
            corpus_review_status={slug: "pending" for slug in _BATCH},
        )
        assert {v.blocked_reason for v in report.off_path} == {"review_status_not_approved"}
        assert all(v.backfill_stamped is False for v in report.off_path)

    def test_human_rejected_candidate_is_never_promoted(self) -> None:
        """사람이 반려한 후보는 승격되지 않는다 — 기계가 그 판정을 뒤집지 않는다."""
        verdicts = {slug: "approved" for slug in _BATCH}
        verdicts[_BATCH[0]] = "rejected"
        report = _eval(human_verdicts=verdicts)
        assert [v.blocked_reason for v in report.off_path] == ["human_verdict_rejected"]
        assert report.approved is False


class TestBackfillAuditStatusIsNotDiscarded:
    """[2026-09-01 codex P1 ②] 감사로그의 **각인값**을 보존해야 잡히는 형태들.

    slug 집합으로 축약하면 "이전 백필이 pending을 각인했는데 나중에 코퍼스만 손으로
    approved가 된" 상태가 그대로 통과한다 — 백필 각인과 손각인을 구분한다는 이 모듈의 존재
    이유가 정확히 그 지점에서 무너진다. 그래서 값 보존을 음성 대조로 동결한다.
    """

    def test_audit_pending_but_corpus_approved_is_blocked(self) -> None:
        """감사=pending · 코퍼스=approved → 차단(각인 이후 손편집 의심).

        이 케이스가 **핵심 회귀 감지 지점**이다: 감사 로더가 status를 버리고 slug만 남기면
        `backfill_stamped`가 참이 되어 그대로 승격된다.
        """
        report = _eval(
            backfilled_status={slug: "pending" for slug in _BATCH},
            corpus_review_status={slug: "approved" for slug in _BATCH},
        )
        assert {v.blocked_reason for v in report.off_path} == {"review_status_audit_mismatch"}
        assert report.approved is False

    def test_mismatch_reason_is_separate_from_not_backfilled(self) -> None:
        """ "각인 안 됨"과 "각인값이 코퍼스값과 다름"은 조치가 달라 사유를 분리한다.

        전자는 백필 CLI 재실행이고 후자는 변경 이력 조사다 — 같은 글자로 보고하면 운영자가
        틀린 조치를 한다.
        """
        mixed = {slug: "approved" for slug in _BATCH}
        mixed[_BATCH[0]] = "rejected"  # 감사=rejected · 코퍼스=approved → 불일치
        report = _eval(backfilled_status=mixed)
        reasons = {v.slug: v.blocked_reason for v in report.off_path}
        assert reasons == {_BATCH[0]: "review_status_audit_mismatch"}

    def test_audit_status_is_carried_into_the_report(self) -> None:
        """감사 각인값이 리포트에 실린다 — 값을 버리지 않았음을 산출물이 자백한다."""
        report = _eval(backfilled_status={slug: "pending" for slug in _BATCH})
        row = report.verdicts[0].to_json()
        assert row["backfill_review_status"] == "pending"
        assert row["backfill_stamped"] is False


class TestReviewQueueIsInformationOnly:
    """[2026-09-01 codex P1 ①] 검수 큐 멤버십은 **정보**지 차단 조건이 아니다.

    큐(비수용 후보)와 코퍼스(수용 후보)는 파이프라인상 서로소라, 큐 멤버십을 승격 전제로
    걸면 게이트가 실제 산출물을 **한 건도** 통과시키지 못한다(항상 exit 1). 동시에 큐 이력은
    검수자에게 의미가 있어 버리지 않는다 — 그 두 가지를 함께 동결한다.
    """

    def test_absence_from_queue_does_not_block(self) -> None:
        """큐에 없는 후보(= 정상 수용분)가 통과한다 — 이것이 P1의 직접 회귀 감지."""
        report = _eval(queue_slugs=set())
        assert report.off_path == []
        assert report.approved is True

    def test_queue_history_is_reported_but_not_blocking(self) -> None:
        """한때 큐에 올랐다 수용된 후보(재제출)도 통과하되, 그 이력은 리포트에 남는다."""
        report = _eval(queue_slugs={_BATCH[0]})
        assert report.off_path == []
        assert report.approved is True
        assert [v.slug for v in report.previously_queued] == [_BATCH[0]]
        assert report.to_json()["previously_queued"] == 1

    def test_queue_history_is_rendered_as_non_blocking(self) -> None:
        """렌더에도 '차단 아님'이 명시된다 — 운영자가 이력을 거부 사유로 오독하지 않게."""
        rendered = render_gate_report(_eval(queue_slugs={_BATCH[0]}))
        assert "참고 — 검수 큐 이력이 있는 제안(차단 아님)" in rendered
        assert f"- `{_BATCH[0]}`" in rendered


class TestWilsonGate:
    """④단 — 결함율은 점추정이 아니라 **상한**으로 판정한다."""

    def test_small_clean_batch_cannot_prove_absence_of_defects(self) -> None:
        """무결점 5건은 통과 못 한다 — 작은 표본의 0/5를 '결함 0%'로 읽지 않는다(설계).

        하한을 썼다면 0/5가 0.0으로 나와 그대로 통과한다 — 이 단언이 방향 오류를 잡는다.
        """
        small = tuple(f"s-{i}" for i in range(5))
        report = _eval(small)
        assert report.off_path == []  # 경로 3단은 전건 통과
        assert report.defect_rate_upper == pytest.approx(0.3511, abs=1e-3)
        assert report.wilson_passed is False
        assert report.approved is False

    def test_defect_rate_denominator_is_human_reviewed_only(self) -> None:
        """분모는 *사람 검수를 받은* 제안뿐 — 미검수를 '결함 없음'으로 세지 않는다."""
        report = _eval(human_verdicts={_BATCH[0]: "approved"})
        assert report.reviewed == 1
        assert report.defects == 0

    def test_zero_reviewed_is_unmeasured_not_pass(self) -> None:
        """사람 판정 0건이면 결함율은 None(측정 불가) — 통과가 아니다."""
        report = _eval(human_verdicts={})
        assert report.defect_rate_upper is None
        assert report.wilson_passed is False


class TestReviewBatchDenominator:
    """[EOS-136 ③] ④단 분모 = 검수 배치 전체 — 제안에서 빠진 결함도 센다.

    판정 근거: `docs/standards/review_status_stamping_contract.md` §5. 핵심 회귀 감지 지점은
    "승인분만 제안하면 통과"가 다시 열리는가다 — 분모를 제안으로 되돌리면 아래 첫 테스트가 빨개진다.
    """

    def test_rejections_left_out_of_the_proposal_still_count(self) -> None:
        """200 승인 제안 + 제안 밖 반려 5 → 5/205 상한 0.0492 > 0.02로 거부(제안 분모면 0/200 통과)."""
        batch = {slug: "approved" for slug in _BATCH}
        batch.update({f"rej-{i}": "rejected" for i in range(5)})
        report = _eval(human_verdicts=batch)
        assert report.off_path == []  # 제안 200건은 경로 3단을 전부 통과했다
        assert report.reviewed == 205 and report.defects == 5
        assert report.defect_rate_upper == pytest.approx(wilson_upper_bound(5, 205, 0.95))
        assert report.wilson_passed is False and report.approved is False

    def test_edited_approvals_are_as_found_defects(self) -> None:
        """손질 승인은 손질 전 내용이 결함이었다 — 제안 밖에 있어도 분자에 들어간다."""
        batch = {slug: "approved" for slug in _BATCH}
        batch.update({f"edit-{i}": "approved_with_edit" for i in range(5)})
        report = _eval(human_verdicts=batch)
        assert report.batch_edited == 5 and report.batch_rejected == 0
        assert report.defects == 5 and report.wilson_passed is False

    def test_as_found_defect_vocabulary_is_rejection_plus_edit(self) -> None:
        """분자의 어휘는 반려 + 손질 승인이다(골든 계약 as-found와 같은 규칙) — 줄이면 빨개진다."""
        assert AS_FOUND_DEFECT_VERDICTS == frozenset({"rejected", "approved_with_edit"})

    def test_mp03_section_4_3_example_is_now_refused(self) -> None:
        """300건 검수·30건 반려 배치에서 승인 270건만 제안 — 제안 분모면 0/270(0.0099) 통과였다."""
        approved = tuple(f"ok-{i:03d}" for i in range(270))
        batch = {slug: "approved" for slug in approved}
        batch.update({f"rej-{i:02d}": "rejected" for i in range(30)})
        report = _eval(approved, human_verdicts=batch)
        assert report.off_path == []
        assert report.defect_rate_upper == pytest.approx(0.1322, abs=1e-4)
        assert report.approved is False
        # 대조: 같은 제안을 제안 분모로 쟀다면 통과했을 값이다(이 판정이 막는 형태).
        assert wilson_upper_bound(0, 270, 0.95) <= 0.02

    def test_a_measured_defect_can_ride_a_passing_batch(self) -> None:
        """결함 1건 허용 222건 — 배치 분모에서만 성립하는 문장이다(제안 분모는 결함을 못 센다)."""
        approved = tuple(f"ok-{i:03d}" for i in range(221))
        batch = {slug: "approved" for slug in approved}
        batch["rej-0"] = "rejected"
        report = _eval(approved, human_verdicts=batch)
        assert report.reviewed == 222 and report.defects == 1
        assert report.approved is True

    def test_report_discloses_the_denominator(self) -> None:
        """분모가 무엇이었는지 산출물이 자백한다 — 범위 표식·제안 밖 수·결함 내역."""
        batch = {slug: "approved" for slug in _BATCH}
        batch.update({"rej-0": "rejected", "edit-0": "approved_with_edit"})
        report = _eval(human_verdicts=batch)
        payload = report.to_json()
        assert payload["defect_scope"] == "review_batch"
        assert payload["batch_outside_proposal"] == 2
        assert (payload["batch_rejected"], payload["batch_edited"], payload["defects"]) == (1, 1, 2)
        rendered = render_gate_report(report)
        assert "검수 배치 202건(제안 밖 2건 포함)" in rendered
        assert "as-found 결함 2건(최신 반려 1 · 손질 대기 1 · 손질 후 재승인 0)" in rendered

    def test_reapproval_after_a_fix_does_not_erase_the_as_found_defect(self) -> None:
        """손질 → 재검수(approved)는 승격 경로지만 배치 결함은 남는다(이력 기준 분자).

        최신 판정만 세면 200건 중 5건을 손질·재승인한 배치가 0/200(0.0133)으로 통과한다 — 손질이
        잦은 생성기의 배치가 무결점으로 보이는 형태다. 이력을 넘기면 5/200(0.0505)로 거부된다.
        """
        latest = {slug: "approved" for slug in _BATCH}  # 5건은 손질 후 재승인되어 최신이 approved
        fixed = set(_BATCH[:5])
        with_history = _eval(human_verdicts=latest, as_found_defective=fixed)
        latest_only = _eval(human_verdicts=latest)
        assert with_history.off_path == []  # ②단은 최신 판정(approved)으로 통과한다
        assert with_history.batch_reapproved == 5 and with_history.defects == 5
        assert with_history.defect_rate_upper == pytest.approx(0.0505, abs=1e-4)
        assert with_history.wilson_passed is False
        # 대조: 이력 없이 최신 판정만 넘기면 같은 배치가 0/200으로 통과한다.
        assert latest_only.defects == 0 and latest_only.wilson_passed is True


class TestEditedApprovalIsNotPromotable:
    """[EOS-136] 손질 승인은 ②단 통과가 아니다 — 각인·코퍼스가 approved여도 막힌다."""

    def test_edited_approval_is_blocked_at_stage_two(self) -> None:
        verdicts = {slug: "approved" for slug in _BATCH}
        verdicts[_BATCH[0]] = "approved_with_edit"
        report = _eval(human_verdicts=verdicts)  # 감사·코퍼스는 전건 approved(손각인 가정)
        assert [(v.slug, v.blocked_reason) for v in report.off_path] == [
            (_BATCH[0], "human_verdict_needs_edit")
        ]

    def test_only_an_as_is_approval_certifies_current_content(self) -> None:
        """각인 도구와 공유하는 술어 — approved만 참이다."""
        assert certifies_current_content("approved") is True
        for verdict in ("approved_with_edit", "rejected", None):
            assert certifies_current_content(verdict) is False


class TestSingleVerdictAuthority:
    """판정 해석은 한 함수 — 이벤트 투영(`_human_verdicts`)과 전체 이벤트판이 같은 집합을 낸다."""

    def test_cli_counts_the_defect_history_not_just_the_latest_verdict(
        self, tmp_path: Path
    ) -> None:
        """CLI 관통 — 반려 후 재승인된 제안은 ②단을 통과하되 ④단 분자에 남는다."""
        args = _fixture_files(tmp_path, _BATCH)
        events = tmp_path / "review_timer.jsonl"
        rejected_first = [
            json.dumps(
                {
                    "review_session_id": f"00000000-0000-4000-9000-{i:012d}",
                    "cu_slug": slug,
                    "reviewer_id": "kiki",
                    "event_type": "finished",
                    "verdict": "rejected",
                    "failure_code": "F2",
                }
            )
            for i, slug in enumerate(_BATCH[:5])
        ]
        # 반려가 먼저, 재승인(원 픽스처의 approved 종결)이 나중 — 최신 판정은 approved다.
        events.write_text(
            "\n".join(rejected_first) + "\n" + events.read_text(encoding="utf-8"), encoding="utf-8"
        )
        report_path = tmp_path / "gate.json"
        assert main([*args, "--json", str(report_path)]) == 1
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["off_path"] == 0
        assert (payload["defects"], payload["batch_reapproved"]) == (5, 5)
        assert payload["wilson_passed"] is False

    def test_projection_matches_latest_events_and_keeps_first_seen_order(
        self, tmp_path: Path
    ) -> None:
        events = tmp_path / "events.jsonl"
        rows = [
            ("wm-b", "finished", "approved"),
            ("wm-a", "finished", "rejected"),
            ("wm-b", "finished", "rejected"),  # 재검수 — 값만 갱신, 순서는 첫 등장
            ("wm-c", "started", None),
        ]
        events.write_text(
            "".join(
                json.dumps(
                    {
                        "review_session_id": f"00000000-0000-4000-8000-{i:012d}",
                        "cu_slug": slug,
                        "reviewer_id": "kiki",
                        "event_type": etype,
                        **({"verdict": verdict} if verdict else {}),
                        **({"failure_code": "F2"} if verdict == "rejected" else {}),
                    }
                )
                + "\n"
                for i, (slug, etype, verdict) in enumerate(rows)
            ),
            encoding="utf-8",
        )
        latest, errors = latest_human_verdict_events([events])
        projected, projected_errors = _human_verdicts([events])
        assert errors == projected_errors == []
        assert list(latest) == ["wm-b", "wm-a"]
        assert projected == {slug: str(event.verdict) for slug, event in latest.items()}
        assert projected == {"wm-b": "rejected", "wm-a": "rejected"}


class TestDamagedInputInvalidatesTheVerdict:
    """[2026-09-01 codex P1 ③] 입력 손상은 판정보다 앞선다 — 손상 위의 통과는 없다."""

    def test_load_error_makes_the_report_not_approved(self) -> None:
        """4단을 전부 통과해도 로드 실패 1행이면 `approved`가 아니다."""
        report = _eval(load_errors=["acc.jsonl line 7: JSONDecodeError"])
        assert report.off_path == []
        assert report.wilson_passed is True
        assert report.input_damaged is True
        assert report.approved is False  # 손상 위의 '허용'은 권위가 없다

    def test_render_names_file_line_and_reason(self) -> None:
        """어느 파일 몇 번째 줄이 왜 실패했는지가 리포트에 남는다(침묵 실패 금지)."""
        rendered = render_gate_report(_eval(load_errors=["acc.jsonl line 7: JSONDecodeError"]))
        assert "입력 오류 — 판정 재료 손상" in rendered
        assert "acc.jsonl line 7: JSONDecodeError" in rendered


class TestReportRendering:
    """리포트가 이 게이트의 성격을 매번 명기한다(선언을 코드가 붙든다)."""

    def test_report_carries_human_review_notice_and_path(self) -> None:
        """법정·검수 절차의 기계 대체 금지 고지 + 정본 경로 4단이 산출물에 실린다."""
        rendered = render_gate_report(_eval())
        assert HUMAN_REVIEW_NOTICE in rendered
        assert "법정·검수 절차의 기계 대체 금지" in HUMAN_REVIEW_NOTICE
        assert "① 코퍼스 실재" in rendered
        assert "검수 큐 등재가 아니다" in rendered  # P1 ①의 정정이 산출물에 자백된다
        assert "④ Wilson 결함율 상한 게이트" in rendered
        assert "검수 배치 전체" in rendered  # EOS-136 ③ 판정이 산출물에 자백된다

    def test_unmeasured_is_rendered_as_such(self) -> None:
        """분모 0은 '0.0000'이 아니라 '측정 불가'로 렌더된다 — 두 상태가 같은 글자면 위장이다."""
        rendered = render_gate_report(_eval(human_verdicts={}))
        assert "측정 불가" in rendered


# ══════════════════════════════════════════════════════════════════════════
# CLI — exit 코드와 쓰기 경로 부재
# ══════════════════════════════════════════════════════════════════════════
def _corpus_row(slug: str) -> dict[str, object]:
    """게이트 CLI 픽스처의 코퍼스 레코드 — 검수자가 본 내용이자 지문의 입력(EOS-27)."""
    return {
        "slug": slug,
        "question_text": f"{slug} 문항",
        "answer": "3",
        "review_status": "approved",
    }


def _fixture_files(
    tmp_path: Path,
    slugs: tuple[str, ...],
    *,
    stamped: bool = True,
    audit_status: str = "approved",
) -> list[str]:
    """게이트 입력 5종(제안·검수 큐·검수 이벤트·코퍼스·백필 감사로그)을 실 형식으로 만든다.

    **검수 큐의 slug는 제안·코퍼스와 겹치지 않는다** — 축적 CLI가 비수용분만 큐로, 수용분만
    코퍼스로 보내므로 그것이 실물의 모양이다. 겹치게 만들면(초판 픽스처) 실제로는 불가능한
    상태를 게이트가 요구해도 테스트가 초록이 된다(2026-09-01 codex P1 ①).
    """
    proposal = tmp_path / "proposal.txt"
    proposal.write_text("# 승격 제안\n" + "\n".join(slugs) + "\n", encoding="utf-8")

    queue = tmp_path / "acc.review.jsonl"
    queue.write_text(
        "\n".join(
            json.dumps(
                {"status": "needs_review", "slug": slug, "reasons": [], "run_id": "run-1"},
                ensure_ascii=False,
            )
            for slug in _QUEUE_ONLY
        )
        + "\n",
        encoding="utf-8",
    )

    events = tmp_path / "review_timer.jsonl"
    events.write_text(
        "\n".join(
            json.dumps(
                {
                    "review_session_id": f"00000000-0000-4000-8000-{i:012d}",
                    "cu_slug": slug,
                    "reviewer_id": "kiki",
                    "event_type": "finished",
                    "verdict": "approved",
                    # 검수 CLI가 실제로 싣는 값 — 검수자가 본 레코드의 지문(EOS-27). 이것이 없는
                    # 판정은 `review_fingerprint_unverifiable`로 막힌다.
                    "content_fingerprint": review_content_fingerprint(_corpus_row(slug)),
                },
                ensure_ascii=False,
            )
            for i, slug in enumerate(slugs)
        )
        + "\n",
        encoding="utf-8",
    )

    corpus = tmp_path / "acc.jsonl"
    corpus.write_text(
        "\n".join(json.dumps(_corpus_row(slug), ensure_ascii=False) for slug in slugs) + "\n",
        encoding="utf-8",
    )

    audit = tmp_path / "backfill_audit.jsonl"
    audit_slugs = slugs if stamped else ()
    audit.write_text(
        "".join(
            json.dumps({"slug": slug, "review_status": audit_status}, ensure_ascii=False) + "\n"
            for slug in audit_slugs
        ),
        encoding="utf-8",
    )

    return [
        "--proposal",
        str(proposal),
        "--review-queue",
        str(queue),
        "--review-events",
        str(events),
        "--corpus",
        str(corpus),
        "--backfill-audit",
        str(audit),
    ]


class TestCliExitCodes:
    def test_full_path_batch_exits_0(self, tmp_path: Path) -> None:
        """정본 경로 전건 + 충분 표본 → exit 0(제안 slug는 큐에 없다 — 실물의 모양)."""
        assert main(_fixture_files(tmp_path, _BATCH)) == 0

    def test_off_path_promotion_exits_1(self, tmp_path: Path) -> None:
        """경로 밖 승격(백필 미경유·손각인)은 exit 1 — ③의 핵심 계약."""
        assert main(_fixture_files(tmp_path, _BATCH, stamped=False)) == 1

    def test_audit_status_mismatch_exits_1(self, tmp_path: Path) -> None:
        """감사=pending · 코퍼스=approved → exit 1(감사값을 버리면 exit 0이 된다)."""
        args = _fixture_files(tmp_path, _BATCH, audit_status="pending")
        assert main(args) == 1

    def test_missing_input_is_input_error_exit_2(self, tmp_path: Path) -> None:
        """입력 부재는 판정이 아니라 **입력 오류(exit 2)** — 판정 실패와 구분한다."""
        args = _fixture_files(tmp_path, _BATCH)
        (tmp_path / "acc.jsonl").unlink()
        assert main(args) == 2

    def test_empty_proposal_is_input_error_not_pass(self, tmp_path: Path) -> None:
        """제안 0건은 '전건 통과'가 아니다 — 판정할 대상이 없으면 exit 2."""
        args = _fixture_files(tmp_path, _BATCH)
        (tmp_path / "proposal.txt").write_text("# 주석뿐\n\n", encoding="utf-8")
        assert main(args) == 2

    def test_small_clean_batch_exits_1(self, tmp_path: Path) -> None:
        """무결점 5건 배치도 Wilson 상한 미달로 exit 1(설계 — 작은 표본은 증명이 아니다)."""
        assert main(_fixture_files(tmp_path, tuple(f"s-{i}" for i in range(5)))) == 1


class TestCliDamagedInputIsExit2:
    """[2026-09-01 codex P1 ③] 손상된 입력에서 exit 0이 나오지 않는다.

    초판은 `load_errors`를 리포트에 렌더만 하고 반환값에 반영하지 않아, 4단을 통과한 배치는
    입력이 깨져 있어도 exit 0이었다. 게이트에서 "읽다가 실패했지만 통과"는 존재할 수 없다.
    """

    @pytest.mark.parametrize(
        "filename",
        ["acc.jsonl", "acc.review.jsonl", "review_timer.jsonl", "backfill_audit.jsonl"],
        ids=["코퍼스", "검수큐", "검수이벤트", "백필감사"],
    )
    def test_one_malformed_line_in_any_input_exits_2(self, tmp_path: Path, filename: str) -> None:
        """입력 4종 어디든 깨진 행이 1건 있으면 exit 2 — 어느 파일이든 재료 손상은 손상이다."""
        args = _fixture_files(tmp_path, _BATCH)
        target = tmp_path / filename
        target.write_text(target.read_text(encoding="utf-8") + "{잘린 행\n", encoding="utf-8")
        assert main(args) == 2

    def test_truncated_rejection_row_does_not_leave_stale_approval(self, tmp_path: Path) -> None:
        """구체 위험형 — *뒤쪽 반려 행*이 잘리면 이전 승인이 최신 판정으로 남는다.

        `_human_verdicts`는 파일 순서상 마지막 종결을 채택하므로, 반려 행이 파싱 실패로
        스킵되면 그 CU는 여전히 approved다. 손상을 무시하면 이것이 **조용히 승격**된다.
        """
        args = _fixture_files(tmp_path, _BATCH)
        events = tmp_path / "review_timer.jsonl"
        events.write_text(
            events.read_text(encoding="utf-8")
            + '{"review_session_id": "00000000-0000-4000-8000-000000009999", '
            + f'"cu_slug": "{_BATCH[0]}", "reviewer_id": "kiki", "event_type": "finis',
            encoding="utf-8",
        )
        assert main(args) == 2  # 손상 무시 시 exit 0(= 반려당한 후보가 승격)

    def test_audit_row_without_status_is_damage_not_a_stamp(self, tmp_path: Path) -> None:
        """감사 행에 `review_status`가 없으면 '각인 기록 있음'이 아니라 손상이다(exit 2)."""
        args = _fixture_files(tmp_path, _BATCH)
        audit = tmp_path / "backfill_audit.jsonl"
        audit.write_text(
            json.dumps({"slug": _BATCH[0]}, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        assert main(args) == 2

    def test_damage_report_names_file_line_and_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """손상 신고가 파일명·줄 번호·예외 타입명을 담는다(무타입 경고 금지)."""
        args = _fixture_files(tmp_path, _BATCH)
        corpus = tmp_path / "acc.jsonl"
        corpus.write_text(corpus.read_text(encoding="utf-8") + "{잘린 행\n", encoding="utf-8")
        assert main(args) == 2
        out = capsys.readouterr().out
        assert "acc.jsonl line 201: JSONDecodeError" in out
        assert "판정 재료 손상" in out

    def test_json_report_persists_even_on_input_error(self, tmp_path: Path) -> None:
        """exit 2에서도 `--json` 리포트가 남는다 — 실패해도 증거가 남아야 한다(2026-08-22)."""
        args = _fixture_files(tmp_path, _BATCH)
        corpus = tmp_path / "acc.jsonl"
        corpus.write_text(corpus.read_text(encoding="utf-8") + "{잘린 행\n", encoding="utf-8")
        report_path = tmp_path / "리포트" / "gate.json"
        assert main([*args, "--json", str(report_path)]) == 2
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["input_damaged"] is True
        assert payload["approved"] is False
        assert payload["load_errors"]


class TestNoMachineSubstitutionForHumanReview:
    """법정·검수 절차의 기계 대체 금지 — 구조로 확인한다(산문 선언만으로는 부족)."""

    def test_cli_has_no_human_review_bypass_flag(self, tmp_path: Path) -> None:
        """ⓑ 사람 판정을 끄는 플래그가 없다 — 있으면 인자 파싱이 성공해 SystemExit 2가 안 난다."""
        base = _fixture_files(tmp_path, _BATCH)
        for flag in ("--force", "--skip-review", "--no-human-verdict", "--assume-approved"):
            with pytest.raises(SystemExit) as excinfo:
                main([*base, flag])
            assert excinfo.value.code == 2  # argparse 인자 오류 — 그런 우회 인자는 존재하지 않는다

    def test_gate_never_writes_to_its_inputs(self, tmp_path: Path) -> None:
        """ⓒ 쓰기 경로 없음 — 실행 후 입력 5종이 **바이트 불변**이다(승격 집행은 사람 몫)."""
        args = _fixture_files(tmp_path, _BATCH)
        inputs = sorted(tmp_path.iterdir())
        before = {path.name: path.read_bytes() for path in inputs}
        assert main(args) == 0
        after = {path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())}
        assert after == before  # 새 파일도 없고(--json 미지정) 기존 파일도 안 고친다

    def test_started_event_alone_is_not_a_human_verdict(self, tmp_path: Path) -> None:
        """ⓐ 검수 *착수*는 판정이 아니다 — started만 있는 후보는 거부된다(미측정≠승인)."""
        args = _fixture_files(tmp_path, _BATCH)
        events = tmp_path / "review_timer.jsonl"
        events.write_text(
            "\n".join(
                json.dumps(
                    {
                        "review_session_id": f"00000000-0000-4000-8000-{i:012d}",
                        "cu_slug": slug,
                        "reviewer_id": "kiki",
                        "event_type": "started",
                    },
                    ensure_ascii=False,
                )
                for i, slug in enumerate(_BATCH)
            )
            + "\n",
            encoding="utf-8",
        )
        assert main(args) == 1


# ══════════════════════════════════════════════════════════════════════════
# EOS-27 — ②단 내용 지문 대조
# ══════════════════════════════════════════════════════════════════════════
_FP_OK = "sha256:" + "a" * 64
_FP_EDITED = "sha256:" + "b" * 64


class TestContentFingerprintStage:
    """판정이 본 내용과 코퍼스 현재 내용이 같은가 — 순수 단(`evaluate_promotion`) 음성/양성 쌍."""

    @staticmethod
    def _fps(slugs: tuple[str, ...] = _BATCH, **per_slug: object) -> dict[str, dict[str, object]]:
        """기본은 전건 일치(리뷰 지문 = 코퍼스 지문). per_slug로 한 건씩만 어긋나게 한다."""
        review: dict[str, object] = {slug: _FP_OK for slug in slugs}
        corpus: dict[str, object] = {slug: _FP_OK for slug in slugs}
        for slug, spec in per_slug.items():
            key = slug.replace("_", "-")
            review[key], corpus[key] = spec  # type: ignore[misc]
        return {"review_fingerprints": review, "corpus_fingerprints": corpus}

    def test_positive_control_matching_fingerprints_stay_on_path(self) -> None:
        report = _eval(**self._fps())  # type: ignore[arg-type]
        assert report.fingerprint_checked is True
        assert report.off_path == [] and report.approved is True
        assert {v.fingerprint_state for v in report.verdicts} == {"match"}

    def test_content_edited_after_approval_is_blocked_with_its_own_reason(self) -> None:
        target = _BATCH[7]
        report = _eval(**self._fps(**{target.replace("-", "_"): (_FP_OK, _FP_EDITED)}))  # type: ignore[arg-type]
        assert [(v.slug, v.blocked_reason) for v in report.off_path] == [
            (target, "review_content_changed")
        ]
        assert report.approved is False
        blocked = report.off_path[0]
        assert (blocked.review_fingerprint, blocked.corpus_fingerprint) == (_FP_OK, _FP_EDITED)
        assert blocked.fingerprint_state == "changed"

    def test_verdict_without_fingerprint_is_unverifiable_not_a_pass(self) -> None:
        target = _BATCH[3]
        report = _eval(**self._fps(**{target.replace("-", "_"): (None, _FP_OK)}))  # type: ignore[arg-type]
        assert [(v.slug, v.blocked_reason) for v in report.off_path] == [
            (target, "review_fingerprint_unverifiable")
        ]
        assert report.off_path[0].fingerprint_state == "unknown"

    def test_both_sides_missing_is_unknown_never_match(self) -> None:
        """None == None이 일치로 읽히는 우연을 막는다 — 지문이 아무 데도 없는 판정은 모름이다."""
        target = _BATCH[0]
        report = _eval(**self._fps(**{target.replace("-", "_"): (None, None)}))  # type: ignore[arg-type]
        assert report.off_path[0].blocked_reason == "review_fingerprint_unverifiable"

    def test_unchecked_mode_is_declared_not_silently_passed(self) -> None:
        """지문 맵을 안 넘기면 대조를 건너뛰되, 건너뛴 사실이 리포트·JSON·렌더에 자백된다."""
        report = _eval()  # 지문 인자 없음
        assert report.fingerprint_checked is False
        assert {v.fingerprint_state for v in report.verdicts} == {"not_checked"}
        assert report.to_json()["fingerprint_checked"] is False
        assert "미수행" in render_gate_report(report)
        checked = _eval(**self._fps())  # type: ignore[arg-type]
        assert "미수행" not in render_gate_report(checked)

    @pytest.mark.parametrize("only", ["review_fingerprints", "corpus_fingerprints"])
    def test_half_a_comparison_is_refused(self, only: str) -> None:
        """한쪽 맵만 오면 대조는 수행될 수 없는데 수행된 것처럼 보인다 — 조용히 건너뛰지 않고 거부."""
        with pytest.raises(ValueError, match="함께"):
            _eval(**{only: {slug: _FP_OK for slug in _BATCH}})  # type: ignore[arg-type]

    def test_earlier_stages_keep_precedence(self) -> None:
        """반려·손질 승인·판정 없음·코퍼스 부재는 지문 사유보다 먼저 보고된다(조치가 다르다)."""
        rejected, edited = _BATCH[0], _BATCH[1]
        report = _eval(
            human_verdicts={
                **{slug: "approved" for slug in _BATCH},
                rejected: "rejected",
                edited: "approved_with_edit",
            },
            review_fingerprints={slug: None for slug in _BATCH},  # 전부 '모름'이어도
            corpus_fingerprints={slug: _FP_OK for slug in _BATCH},
        )
        reasons = {v.slug: v.blocked_reason for v in report.verdicts}
        assert reasons[rejected] == "human_verdict_rejected"
        assert reasons[edited] == "human_verdict_needs_edit"
        assert reasons[_BATCH[2]] == "review_fingerprint_unverifiable"

    def test_fingerprint_stage_precedes_the_audit_stages(self) -> None:
        """내용이 바뀐 건은 ③단(감사로그 대조)이 통과로 보이더라도 막힌다 — 그것이 사각이었다."""
        target = _BATCH[5]
        report = _eval(**self._fps(**{target.replace("-", "_"): (_FP_OK, _FP_EDITED)}))  # type: ignore[arg-type]
        blocked = next(v for v in report.verdicts if v.slug == target)
        assert blocked.backfill_review_status == "approved"  # ③단 재료는 멀쩡하다
        assert blocked.corpus_review_status == "approved"
        assert blocked.blocked_reason == "review_content_changed"


class TestContentFingerprintCli:
    """CLI 관통 — 이벤트 JSONL·코퍼스 JSONL에서 지문을 읽어 exit 코드를 낸다."""

    @staticmethod
    def _report(tmp_path: Path, args: list[str]) -> tuple[int, dict[str, object]]:
        report_path = tmp_path / "gate.json"
        code = main([*args, "--json", str(report_path)])
        return code, json.loads(report_path.read_text(encoding="utf-8"))

    @staticmethod
    def _reasons(payload: dict[str, object]) -> dict[str, str | None]:
        return {row["slug"]: row["blocked_reason"] for row in payload["verdicts"]}  # type: ignore[index, union-attr]

    def test_untouched_batch_passes_and_reports_the_check_ran(self, tmp_path: Path) -> None:
        code, payload = self._report(tmp_path, _fixture_files(tmp_path, _BATCH))
        assert code == 0 and payload["fingerprint_checked"] is True

    def test_content_edit_after_approval_exits_1_for_that_slug_only(self, tmp_path: Path) -> None:
        args = _fixture_files(tmp_path, _BATCH)
        corpus = tmp_path / "acc.jsonl"
        edited = _BATCH[11]
        rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row["slug"] == edited:
                row["answer"] = "999"  # 승인 뒤 정답을 몰래 바꿨다
        corpus.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

        code, payload = self._report(tmp_path, args)

        assert code == 1
        reasons = self._reasons(payload)
        assert reasons.pop(edited) == "review_content_changed"
        assert set(reasons.values()) == {None}  # 나머지 199건은 경로 내(양성 대조)

    def test_events_without_fingerprints_exit_1_as_unverifiable(self, tmp_path: Path) -> None:
        """옛 이벤트 모사 — 지문 키가 없는 승인 판정은 전건 막힌다(그랜드파더 없음)."""
        args = _fixture_files(tmp_path, _BATCH)
        events = tmp_path / "review_timer.jsonl"
        rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row.pop("content_fingerprint")
        events.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

        code, payload = self._report(tmp_path, args)

        assert code == 1
        assert set(self._reasons(payload).values()) == {"review_fingerprint_unverifiable"}

    def test_review_status_edit_alone_is_not_a_content_change(self, tmp_path: Path) -> None:
        """운영 메타(review_status)만 바뀐 건 내용 변경이 아니다 — ③단의 audit_mismatch가 잡는다.
        두 사유가 섞이면 조치가 갈리는 두 상황(재검수 vs 변경 이력 조사)이 구분되지 않는다."""
        args = _fixture_files(tmp_path, _BATCH)
        corpus = tmp_path / "acc.jsonl"
        text = corpus.read_text(encoding="utf-8")
        victim = _BATCH[2]
        lines = []
        for line in text.splitlines():
            row = json.loads(line)
            if row["slug"] == victim:
                row["review_status"] = "pending"
            lines.append(json.dumps(row, ensure_ascii=False))
        corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

        _code, payload = self._report(tmp_path, args)

        assert self._reasons(payload)[victim] == "review_status_audit_mismatch"
