"""검수 타이머 이벤트 계약 검증 — 3종 폐쇄·교차 필드 강제·F1~F8 소비 (EOS-54 acceptance ①·④).

정본: `schema/review_timer.py`. 핵심 계약 — started/finished/aborted 폐쇄 3종, finished는
판정 필수, rejected는 failure_code(F1~F8 — EOS-51 동결 enum) 필수, elapsed_ms None=미측정
(0 날조 금지). 변별력: 각 규칙마다 **통과/실패 양쪽**을 실측한다(변별력 없는 검증 스텝 금지).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from whymath_backend.schema.enums import (
    GenerationFailureCode,
    ReviewStatus,
    is_review_status_cleared,
)
from whymath_backend.schema.review_timer import (
    CONTENT_FINGERPRINT_PREFIX,
    REVIEW_FINGERPRINT_EXCLUDED_KEYS,
    VERDICT_APPROVED_WITH_EDIT,
    ReviewTimerEvent,
    ReviewTimerEventType,
    ReviewVerdict,
    review_content_fingerprint,
    review_fingerprint_state,
    review_status_for_verdict,
)


def _base(**overrides: Any) -> dict[str, Any]:
    """유효 이벤트 재료 — overrides로 케이스 변형."""
    data: dict[str, Any] = {
        "review_session_id": uuid.uuid4(),
        "cu_slug": "quadratic-roots-001",
        "reviewer_id": "kiki",
        "event_type": "started",
    }
    data.update(overrides)
    return data


class TestEventTypeClosure:
    def test_three_types_frozen(self) -> None:
        """설계서 §6 "시작·종료·중단" — 폐쇄 3종 값집합 동결."""
        assert {m.value for m in ReviewTimerEventType} == {"started", "finished", "aborted"}

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(event_type="paused"))

    def test_extra_field_rejected(self) -> None:
        """extra=forbid — 계약 밖 필드 유입 차단."""
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(student_id=str(uuid.uuid4())))


class TestStartedShape:
    def test_valid_started(self) -> None:
        event = ReviewTimerEvent.model_validate(_base())
        assert event.event_type == "started"  # use_enum_values — 값 문자열 저장
        assert event.verdict is None and event.elapsed_ms is None

    def test_started_rejects_verdict(self) -> None:
        with pytest.raises(ValidationError, match="started"):
            ReviewTimerEvent.model_validate(_base(verdict="approved"))

    def test_started_rejects_elapsed(self) -> None:
        """착수 시점엔 잰 것이 없다 — elapsed 동반 started는 계약 위반."""
        with pytest.raises(ValidationError, match="elapsed_ms"):
            ReviewTimerEvent.model_validate(_base(elapsed_ms=1000))


class TestFinishedShape:
    def test_valid_approved(self) -> None:
        event = ReviewTimerEvent.model_validate(
            _base(event_type="finished", verdict="approved", elapsed_ms=95_000)
        )
        assert event.verdict == "approved"
        assert event.elapsed_ms == 95_000

    def test_finished_requires_verdict(self) -> None:
        """판정 없는 종결 없음 — 그런 상태는 aborted다."""
        with pytest.raises(ValidationError, match="verdict"):
            ReviewTimerEvent.model_validate(_base(event_type="finished"))

    def test_finished_verdict_pending_rejected(self) -> None:
        """pending은 판정이 아니다 — Literal 폐쇄 2종(approved|rejected)."""
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(event_type="finished", verdict="pending"))

    def test_finished_elapsed_none_is_unmeasured_not_zero(self) -> None:
        """acceptance ④ — 계측 실패한 종결은 elapsed=None으로 유효(판정은 남기되 미계측)."""
        event = ReviewTimerEvent.model_validate(
            _base(event_type="finished", verdict="approved", elapsed_ms=None)
        )
        assert event.elapsed_ms is None  # 0이 아니라 None — 집계가 분리 카운트

    def test_negative_elapsed_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="approved", elapsed_ms=-1)
            )


class TestRejectedRequiresFailureCode:
    """설계서 §4 강제 분류 — 반려코드 없는 반려는 생성 자체가 불가(함수 레벨 집행)."""

    def test_rejected_without_code_fails(self) -> None:
        with pytest.raises(ValidationError, match="failure_code"):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="rejected", elapsed_ms=10_000)
            )

    def test_rejected_with_each_frozen_code_passes(self) -> None:
        """F1~F8 동결 8코드 전건 수용 — 이 계약이 GenerationFailureCode의 소비 지점."""
        for code in GenerationFailureCode:
            event = ReviewTimerEvent.model_validate(
                _base(
                    event_type="finished",
                    verdict="rejected",
                    failure_code=code.value,
                    elapsed_ms=10_000,
                )
            )
            assert event.failure_code == code.value

    def test_unknown_code_rejected(self) -> None:
        """계약 밖 코드(F9) 차단 — 폐쇄 8종은 G0 동결(추가는 설계서 개정 전제)."""
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="rejected", failure_code="F9")
            )

    def test_approved_with_code_fails(self) -> None:
        """승인에 반려코드 금지 — 판정과 코드의 모순 조합 차단."""
        with pytest.raises(ValidationError, match="rejected"):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="approved", failure_code="F1")
            )

    def test_note_without_code_fails(self) -> None:
        """자유 텍스트 단독 금지(§4) — note는 코드의 부기로만."""
        with pytest.raises(ValidationError, match="failure_note"):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="approved", failure_note="애매함")
            )

    def test_note_with_code_passes(self) -> None:
        event = ReviewTimerEvent.model_validate(
            _base(
                event_type="finished",
                verdict="rejected",
                failure_code="F3",
                failure_note="2→3단계 비약",
                elapsed_ms=10_000,
            )
        )
        assert event.failure_note == "2→3단계 비약"


class TestAbortedShape:
    def test_valid_aborted_with_partial_elapsed(self) -> None:
        event = ReviewTimerEvent.model_validate(_base(event_type="aborted", elapsed_ms=30_000))
        assert event.elapsed_ms == 30_000

    def test_aborted_rejects_verdict(self) -> None:
        """판정이 있으면 finished다 — aborted+verdict 모순 차단."""
        with pytest.raises(ValidationError, match="aborted"):
            ReviewTimerEvent.model_validate(_base(event_type="aborted", verdict="approved"))

    def test_aborted_rejects_failure_code(self) -> None:
        with pytest.raises(ValidationError, match="aborted"):
            ReviewTimerEvent.model_validate(_base(event_type="aborted", failure_code="F1"))


class TestTimeSeparation:
    """EOS-48 발생/수신 분리 — occurred_at(발생)·recorded_at(수신) 독립 좌석."""

    def test_both_default_none(self) -> None:
        event = ReviewTimerEvent.model_validate(_base())
        assert event.occurred_at is None  # 미신고
        assert event.recorded_at is None  # 적재 계층(DB now()/JSONL append)이 채움

    def test_both_settable_independently(self) -> None:
        occurred = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
        received = datetime(2026, 8, 31, 2, 5, tzinfo=UTC)
        event = ReviewTimerEvent.model_validate(_base(occurred_at=occurred, recorded_at=received))
        assert event.occurred_at == occurred
        assert event.recorded_at == received


class TestIdentityFields:
    def test_cu_slug_width_matches_problem_slug(self) -> None:
        """폭 128 = problem.slug String(128) — 경계 통과/초과 양쪽 실측."""
        ok = ReviewTimerEvent.model_validate(_base(cu_slug="s" * 128))
        assert len(ok.cu_slug) == 128
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(cu_slug="s" * 129))

    def test_reviewer_id_required_nonempty(self) -> None:
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(reviewer_id=""))

    def test_no_student_axis_fields(self) -> None:
        """학생 소유 축 필드 부재 — 검수자 텔레메트리(모듈 docstring 개인정보 판정)."""
        fields = set(ReviewTimerEvent.model_fields)
        assert fields & {"user_id", "student_id", "target_user_id"} == set()


class TestEditAwareVerdictVocabulary:
    """EOS-62 — 판정 3종화. '손질해서 통과시킨 CU'가 무손질 통과와 구분되는가.

    이 해상도가 없으면 "HIT 중앙값 4분 + 승인율 93%"가 성공으로 읽히는데 승인분의 상당수가
    사람 손질일 수 있고, 그 손질분이 정확히 AI-first 전략의 실패 신호다 — 성공 지표가 실패를
    가리는 구조다(N4 갭 ③).
    """

    def test_verdict_vocabulary_is_exactly_three(self) -> None:
        """폐쇄 3종 동결 — 문서 §17의 5종 중 REGENERATE·ESCALATE는 의도적 미채택."""
        assert set(get_args(ReviewVerdict)) == {"approved", "approved_with_edit", "rejected"}

    def test_edit_approval_accepts_optional_failure_code(self) -> None:
        """부기 규약 — 권장하되 강제하지 않는다(코드 없이도 유효)."""
        with_code = ReviewTimerEvent.model_validate(
            _base(
                event_type="finished",
                verdict="approved_with_edit",
                failure_code=GenerationFailureCode.F7,
                elapsed_ms=90_000,
            )
        )
        assert with_code.failure_code == GenerationFailureCode.F7

        without_code = ReviewTimerEvent.model_validate(
            _base(event_type="finished", verdict="approved_with_edit", elapsed_ms=90_000)
        )
        assert without_code.failure_code is None

    def test_edit_approval_allows_note_with_code(self) -> None:
        event = ReviewTimerEvent.model_validate(
            _base(
                event_type="finished",
                verdict="approved_with_edit",
                failure_code=GenerationFailureCode.F3,
                failure_note="3단계 근거 문장을 보강",
            )
        )
        assert event.failure_note is not None

    def test_edit_approval_note_still_requires_a_code(self) -> None:
        """§4 자유 텍스트 단독 금지 — 손질 승인에서도 유지."""
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(
                _base(event_type="finished", verdict="approved_with_edit", failure_note="고침")
            )

    def test_plain_approval_still_forbids_failure_code(self) -> None:
        """무손질 승인에 결함코드를 붙이는 경로를 막는다 — 고쳤다면 값이 틀린 것이다.

        이걸 허용하면 `approved` + code가 사실상 '손질 승인'이 되어 해상도 갭이 되살아난다.
        """
        with pytest.raises(ValidationError, match="무손질 승인"):
            ReviewTimerEvent.model_validate(
                _base(
                    event_type="finished",
                    verdict="approved",
                    failure_code=GenerationFailureCode.F1,
                )
            )

    def test_rejection_still_requires_a_code(self) -> None:
        """반려의 강제 분류(§4)는 불변 — 어휘 확장이 기존 계약을 느슨하게 만들지 않았다."""
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(event_type="finished", verdict="rejected"))

    def test_aborted_still_forbids_the_new_verdict(self) -> None:
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(
                _base(event_type="aborted", verdict="approved_with_edit")
            )

    def test_unknown_verdict_rejected(self) -> None:
        """문서 §17의 미채택 2종은 어휘에 들어오지 않는다(폐쇄 유지)."""
        for outsider in ("escalate", "regenerate", "pending"):
            with pytest.raises(ValidationError):
                ReviewTimerEvent.model_validate(_base(event_type="finished", verdict=outsider))


class TestBackwardCompatibility:
    """acceptance ④ — 기존 `approved` 행의 의미를 바꾸지 않는다(값 추가만·소급 재분류 금지)."""

    def test_existing_approved_rows_still_validate_unchanged(self) -> None:
        """EOS-62 이전에 기록된 무손질 승인 행이 그대로 통과한다."""
        event = ReviewTimerEvent.model_validate(
            _base(event_type="finished", verdict="approved", elapsed_ms=120_000)
        )
        assert event.verdict == "approved"
        assert event.failure_code is None

    def test_approved_is_not_silently_reinterpreted(self) -> None:
        """`approved`는 여전히 '무손질 승인'이지 '손질 여부 미상'으로 바뀌지 않는다.

        어휘가 늘었다고 과거 값의 의미를 재정의하면 12월 판정이 소급 재분류 위에 서게 된다 —
        골든 승격의 `edit_aware_since` 경계도 같은 원칙의 시각 축 표현이다.
        """
        assert review_status_for_verdict("approved") is ReviewStatus.approved


class TestVerdictToReviewStatusBridge:
    """두 축(판정 ↔ 노출 상태)이 갈라진 뒤의 유일한 정본 변환."""

    def test_both_approvals_map_to_approved_status(self) -> None:
        """손질 여부는 생산성 축이지 노출 축이 아니다 — 둘 다 노출 통과."""
        assert review_status_for_verdict("approved") is ReviewStatus.approved
        assert review_status_for_verdict(VERDICT_APPROVED_WITH_EDIT) is ReviewStatus.approved

    def test_mapped_status_passes_the_exposure_predicate(self) -> None:
        """★ 이 변환이 없으면 손질 승인 CU가 **무증상으로 노출에서 빠진다**.

        `is_review_status_cleared`는 `approved`만 True인 fail-closed 술어다. verdict를 그대로
        review_status에 복사하면 `approved_with_edit`가 False로 떨어져 에러 없이 목록에서
        사라진다 — 그 경로가 실제로 침묵 실패임을 여기서 실측 고정한다.
        """
        assert is_review_status_cleared(review_status_for_verdict(VERDICT_APPROVED_WITH_EDIT))
        assert not is_review_status_cleared(VERDICT_APPROVED_WITH_EDIT)  # 직접 복사 = 조용한 탈락

    def test_rejected_maps_to_rejected(self) -> None:
        assert review_status_for_verdict("rejected") is ReviewStatus.rejected

    def test_none_is_undecided_not_a_status(self) -> None:
        assert review_status_for_verdict(None) is None

    def test_unknown_verdict_raises_instead_of_guessing(self) -> None:
        """상류가 확장됐는데 변환이 따라가지 않은 상태를 조용히 통과시키지 않는다."""
        with pytest.raises(ValueError, match="어휘 밖"):
            review_status_for_verdict("escalate")

    def test_review_status_vocabulary_did_not_absorb_the_verdict(self) -> None:
        """`approved_with_edit`는 ReviewStatus에 넣지 않는다 — §13.3 노출 정책 보호."""
        assert VERDICT_APPROVED_WITH_EDIT not in {m.value for m in ReviewStatus}


# ══════════════════════════════════════════════════════════════════════════
# EOS-27 — 검수 내용 지문: 정규화 정본 · 3상태 대조 · 이벤트 필드 계약
# ══════════════════════════════════════════════════════════════════════════
_RECORD: dict[str, Any] = {
    "slug": "wm-fp-0001",
    "question_text": "이차방정식 x^2 - 5x + 6 = 0 의 큰 근을 구하시오.",
    "answer": "3",
    "answer_explanation": "(x-2)(x-3)=0 이므로 큰 근은 3.",
    "verify": {"conditions": "x**2 - 5*x + 6 = 0", "answer_map": {"x": "3"}},
    "hint": ["인수분해를 떠올려 보세요"],  # 검수 화면이 렌더하지 않는 필드(고지만 한다)
}
_FP_A = CONTENT_FINGERPRINT_PREFIX + "a" * 64
_FP_B = CONTENT_FINGERPRINT_PREFIX + "b" * 64


class TestFingerprintNormalization:
    """지문의 정규화 규칙 — 규칙마다 '같아야 할 때 같고 달라야 할 때 다르다'를 양쪽 실측한다."""

    def test_format_is_prefixed_sha256_hex(self) -> None:
        fp = review_content_fingerprint(_RECORD)
        assert fp.startswith(CONTENT_FINGERPRINT_PREFIX)
        assert len(fp) == len(CONTENT_FINGERPRINT_PREFIX) + 64
        # 이벤트 필드 패턴이 이 함수의 출력을 그대로 받는다(둘이 따로 놀지 않는다).
        ReviewTimerEvent.model_validate(_base(content_fingerprint=fp))

    def test_key_order_does_not_change_the_fingerprint(self) -> None:
        """같은 내용이 직렬화 순서만 달라도 같은 지문 — 거짓 '내용 변경' 방지."""
        shuffled = dict(reversed(list(_RECORD.items())))
        assert list(shuffled) != list(_RECORD)
        assert review_content_fingerprint(shuffled) == review_content_fingerprint(_RECORD)

    @pytest.mark.parametrize(
        "edit",
        [
            {"answer": "2"},  # 정답
            {"question_text": "이차방정식 x^2 - 5x + 6 = 0 의 작은 근을 구하시오."},  # 문항
            {"answer_explanation": "(x-2)(x-3)=0 이므로 큰 근은 2."},  # 해설
            {"verify": {"conditions": "x**2 - 5*x + 6 = 0", "answer_map": {"x": "2"}}},  # 중첩
            {"hint": ["정답은 3입니다"]},  # 렌더되지 않는 필드
            {"slug": "wm-fp-0002"},  # 식별자
        ],
        ids=["정답", "문항", "해설", "중첩_검산", "미렌더_힌트", "slug"],
    )
    def test_any_content_edit_changes_the_fingerprint(self, edit: dict[str, Any]) -> None:
        """승인 뒤 어떤 내용 편집도 지문을 바꾼다 — 렌더 축만 해시하면 '미렌더_힌트' 행이 빨개진다."""
        edited = {**_RECORD, **edit}
        assert review_content_fingerprint(edited) != review_content_fingerprint(_RECORD)

    @pytest.mark.parametrize("key", sorted(REVIEW_FINGERPRINT_EXCLUDED_KEYS))
    def test_operational_meta_is_excluded(self, key: str) -> None:
        """검수 뒤 정당한 도구가 쓰는 운영 메타는 지문에 안 든다 — 들어가면 각인 직후 전건이 '변경'."""
        base = review_content_fingerprint(_RECORD)
        assert review_content_fingerprint({**_RECORD, key: "approved"}) == base

    def test_excluded_set_is_exactly_the_documented_one(self) -> None:
        """제외 집합은 좁게 동결 — 키를 더 빼면 그만큼 '승인 뒤 편집 미탐지' 구멍이 생긴다."""
        assert REVIEW_FINGERPRINT_EXCLUDED_KEYS == {
            "review_status",
            "review_score",
            "quarantine_reason",
            "quarantined_at",
            "updated_at",
        }

    def test_top_level_none_equals_absent_key(self) -> None:
        assert review_content_fingerprint({**_RECORD, "tags": None}) == review_content_fingerprint(
            _RECORD
        )

    def test_empty_value_is_not_absent(self) -> None:
        """None만 빠지고 빈 문자열·빈 목록은 내용이다 — 둘을 섞으면 '답을 비운 편집'이 안 보인다."""
        base = review_content_fingerprint(_RECORD)
        assert review_content_fingerprint({**_RECORD, "answer": ""}) != base
        assert review_content_fingerprint({**_RECORD, "tags": []}) != base

    def test_nested_none_is_content(self) -> None:
        """중첩 None은 정규화하지 않는다(최상위만) — 중첩까지 지우면 서로 다른 구조가 같아진다."""
        a = {**_RECORD, "verify": {"answer_map": {"x": None}}}
        b = {**_RECORD, "verify": {"answer_map": {}}}
        assert review_content_fingerprint(a) != review_content_fingerprint(b)

    def test_hangul_is_hashed_as_utf8_not_escaped(self) -> None:
        """한글을 이스케이프하면 직렬화기마다 지문이 갈린다 — UTF-8 원문 기준으로 동결."""
        import hashlib
        import json

        expected = (
            CONTENT_FINGERPRINT_PREFIX
            + hashlib.sha256(
                json.dumps(
                    {"q": "근"}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        )
        assert review_content_fingerprint({"q": "근"}) == expected

    def test_unserializable_value_raises_instead_of_being_stringified(self) -> None:
        """str()로 접으면 서로 다른 객체가 같은 지문을 낸다 — 조용히 접지 않고 TypeError."""
        with pytest.raises(TypeError):
            review_content_fingerprint({"slug": "x", "when": datetime(2026, 9, 1, tzinfo=UTC)})


class TestFingerprintState:
    """3상태 대조 — 모름은 일치가 아니다."""

    def test_match_changed_unknown(self) -> None:
        assert review_fingerprint_state(_FP_A, _FP_A) == "match"
        assert review_fingerprint_state(_FP_A, _FP_B) == "changed"

    @pytest.mark.parametrize(
        ("reviewed", "current"),
        [(None, _FP_A), (_FP_A, None), (None, None)],
        ids=["이벤트_지문없음", "코퍼스_지문없음", "둘다없음"],
    )
    def test_missing_side_is_unknown_never_match(
        self, reviewed: str | None, current: str | None
    ) -> None:
        """None==None 같은 우연한 동치로 'match'가 되지 않는다 — 이 필드가 막으려는 사각 그 자체."""
        assert review_fingerprint_state(reviewed, current) == "unknown"


class TestEventFingerprintField:
    """이벤트 계약 — started·finished만 싣고, aborted는 못 싣고, 기본은 모름(None)."""

    def test_default_is_none_meaning_unknown(self) -> None:
        assert ReviewTimerEvent.model_validate(_base()).content_fingerprint is None

    def test_started_and_finished_accept_it(self) -> None:
        started = ReviewTimerEvent.model_validate(_base(content_fingerprint=_FP_A))
        finished = ReviewTimerEvent.model_validate(
            _base(event_type="finished", verdict="approved", content_fingerprint=_FP_A)
        )
        assert started.content_fingerprint == finished.content_fingerprint == _FP_A

    def test_aborted_rejects_it(self) -> None:
        """판정 없는 중단은 내용을 인증하지 않는다 — 실리면 '인증된 내용'으로 오독된다."""
        with pytest.raises(ValidationError, match="content_fingerprint"):
            ReviewTimerEvent.model_validate(_base(event_type="aborted", content_fingerprint=_FP_A))

    @pytest.mark.parametrize(
        "bad",
        ["", "abc", "sha256:XYZ", "sha256:" + "A" * 64, "md5:" + "a" * 64, "sha256:" + "a" * 63],
        ids=["빈", "짧은", "비16진", "대문자", "다른접두", "63자"],
    )
    def test_malformed_fingerprint_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            ReviewTimerEvent.model_validate(_base(content_fingerprint=bad))

    def test_old_event_without_the_field_still_validates(self) -> None:
        """하위호환 — 지문 키가 없는 옛 JSONL 행이 그대로 읽힌다(그리고 '모름'이 된다)."""
        row = _base(event_type="finished", verdict="approved")
        assert "content_fingerprint" not in row
        assert ReviewTimerEvent.model_validate(row).content_fingerprint is None
