"""S2 생성 *비수용 후보* 검수/진단 워크리스트 — 사람 검수 큐 결선.

배경: `l3/equivalent/orchestrator.run_batch`가 낸 `GenerationOutcome`은 후보(candidate)·게이트
판정(acceptance)·사유(reasons)를 담지만, 배치(`problem_corpus_batch`)는 이를 *사유 문자열만*
남기고 폐기한다 — 검수·진단에 필요한 후보+근거가 휘발한다. `acceptance.py`가 "사람 검수 큐
결선은 후속"으로 남긴 지점이다.

본 모듈은 **비수용 outcome**(status ∉ {accepted_stored, accepted} — 즉 needs_review·
rejected_gate·rejected_duplicate·generation_failed)을 우선순위·근거와 함께 검수자/진단용
워크리스트로 정리한다. 소비처: ① needs_review 후보의 사람 검수(S2 게이트) ② 배치 수율<요청 시
"왜 거부됐나" 진단 ③ 게이트 임계값 보정 입력.

두 계층(EOS-58 codex 리뷰 상환 — 검수 큐의 내구 저장소 부재가 한 뿌리):
  1. **내구 큐 저장소**(`ReviewQueueEntry`·`append_review_queue_jsonl`·`load_review_queue_jsonl`)
     — 비수용 outcome 1건당 JSONL 1행을 **발생 즉시 append+flush**로 영속한다(EOS-55 genlog
     동형). 행에는 **후보 payload 전문**(코퍼스 레코드 JSON — 자체생성물이라 저작권 무관)이
     실려 검수자가 문항·정답·해설을 실제로 볼 수 있다(P1-1). payload가 없는 outcome(생성
     실패)은 실패 사유만 정직 기록한다(없는 본문 날조 금지). 행은 관측이라 삭제·수정하지
     않는다(append-only).
  2. **렌더 뷰**(`render_review_queue_markdown`) — 워크리스트 md는 회차 메모리가 아니라 큐
     저장소 *전체*의 렌더다: 회차 간 누적이 기본이고(P1-2 — 덮어쓰기로 이전 미해결 항목이
     소실되지 않음), 같은 후보 재출현은 payload sha 기준으로 묶어 출현 횟수를 표기한다.

범위 밖 별항(정본화≠집행): 해결(체크 완료) 상태 추적·검수 판정의 `review_status` 각인·코퍼스
승격 집행은 이 모듈 밖이다(OPS-24 백필·승격 후속 태스크 소관) — 이번 계약은 "큐가 소실되지
않고 본문이 실린다"까지다.

구계층(회차 메모리 뷰 — `WorklistItem`·`build_worklist`·`render_worklist_markdown`)은
`problem_corpus_batch --worklist-out`(스켈레톤 경로·수율 100% 설계)이 그대로 소비하므로 유지한다.

검수 큐 규약(`reviewer_sample_package` 미러): **근거만 모으고 판정하지 않는다** — 기계 사유
(reasons·동등성 점수)를 나열하고, needs_review 항목엔 사람 판단 빈 체크박스만 둔다. 렌더는
순수(파일 무관)·학생 비노출(운영 산출물)·"조용한 실패 금지"(모든 사유 보존).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from whymath_backend.l3.equivalent.orchestrator import GenerationOutcome

__all__ = [
    "ReviewQueueEntry",
    "WorklistItem",
    "append_review_queue_jsonl",
    "build_worklist",
    "entry_from_outcome",
    "load_review_queue_jsonl",
    "render_review_queue_markdown",
    "render_worklist_markdown",
]

# 수용(적재/dry 수용)은 워크리스트 대상이 아니다 — 나머지 4종이 검수/진단 대상.
_STORED_STATUSES: frozenset[str] = frozenset({"accepted_stored", "accepted"})

# 우선순위(작을수록 위) — 검수 가치·조치 시급성 순. needs_review(사람 판단 대기)가 최상위,
# 이어 게이트 거부·과유사 거부, 생성 실패는 마지막(후보 자체 없음).
_STATUS_PRIORITY: dict[str, int] = {
    "needs_review": 0,
    "rejected_gate": 1,
    "rejected_duplicate": 2,
    "generation_failed": 3,
}


class WorklistItem(BaseModel):
    """비수용 후보 1건 — 검수/진단 워크리스트 항목(판정 없음·근거만)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str = Field(
        description="outcome 상태(needs_review·rejected_gate·rejected_duplicate·generation_failed)."
    )
    priority: int = Field(description="정렬 우선순위(작을수록 위·상태 기반).")
    slug: str | None = Field(
        default=None,
        description="후보 문제 slug(candidate.problem.slug·생성 실패 등으로 없으면 None).",
    )
    equivalence_score: float | None = Field(
        default=None,
        description="게이트 동등성 가중 점수 0~1(acceptance 있으면·없으면 None).",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="거부/검수/실패 사유 누적(조용한 실패 금지·학생 비노출).",
    )


def _to_item(outcome: GenerationOutcome) -> WorklistItem:
    """비수용 GenerationOutcome → WorklistItem(순수·근거 추출만)."""
    slug = outcome.candidate.problem.slug if outcome.candidate is not None else None
    score = outcome.acceptance.equivalence_score if outcome.acceptance is not None else None
    return WorklistItem(
        status=outcome.status,
        priority=_STATUS_PRIORITY.get(outcome.status, len(_STATUS_PRIORITY)),
        slug=slug,
        equivalence_score=score,
        reasons=list(outcome.reasons),
    )


def build_worklist(outcomes: Iterable[GenerationOutcome]) -> list[WorklistItem]:
    """비수용 outcome을 검수/진단 워크리스트로 정리한다(순수·필터+우선순위 정렬).

    수용(accepted_stored·accepted)은 제외한다 — 나머지 4종만 항목화한다. 정렬은 (우선순위,
    동등성 점수 내림차순, slug) — 같은 상태 안에서는 *수용에 가까운(점수 높은) 후보*를 위로 올려
    검수/구제 가치가 큰 것을 먼저 보게 한다(점수 없으면 뒤로). 결정론(안정 정렬).
    """
    items = [_to_item(o) for o in outcomes if o.status not in _STORED_STATUSES]
    items.sort(key=lambda it: (it.priority, -(it.equivalence_score or 0.0), it.slug or ""))
    return items


def render_worklist_markdown(items: list[WorklistItem], *, total_outcomes: int) -> str:
    """워크리스트를 검수자/진단용 마크다운으로 렌더(순수·판정 없음).

    헤더에 총 outcome 수와 상태별 카운트(검수필요·게이트거부·과유사거부·생성실패)를, 항목마다
    상태·slug·동등성 점수·기계 사유를 낸다. needs_review 항목엔 **사람 판단 빈 체크박스**만 두어
    "근거만 모으고 판정 안 함"(reviewer_sample_package 규약)을 지킨다.
    """
    needs_review = sum(1 for it in items if it.status == "needs_review")
    gate = sum(1 for it in items if it.status == "rejected_gate")
    dup = sum(1 for it in items if it.status == "rejected_duplicate")
    failed = sum(1 for it in items if it.status == "generation_failed")

    lines: list[str] = [
        "# S2 비수용 후보 검수/진단 워크리스트",
        "",
        f"- 총 생성 outcome: {total_outcomes} · 비수용(워크리스트) {len(items)}",
        f"- 상태별: 검수필요 {needs_review} · 게이트거부 {gate} · 과유사거부 {dup} · "
        f"생성실패 {failed}",
        "- 규약: 기계 사유만 모으고 판정하지 않는다 — needs_review는 사람 판단 체크박스로 결선.",
        "",
    ]
    for idx, item in enumerate(items, start=1):
        score = "—" if item.equivalence_score is None else f"{item.equivalence_score:.4f}"
        slug = item.slug or "(slug 없음)"
        lines.append(f"## {idx}. [{item.status}] {slug}")
        lines.append(f"- 동등성 점수: {score}")
        if item.reasons:
            lines.append("- 기계 사유:")
            lines.extend(f"  - {reason}" for reason in item.reasons)
        else:
            lines.append("- 기계 사유: (없음)")
        if item.status == "needs_review":
            lines.append("- 사람 판단(검수자 체크):")
            lines.append("  - [ ] 교육적으로 타당한 동등문제인가")
            lines.append("  - [ ] 수용(코퍼스 편입) / [ ] 반려 / [ ] 임계값 재검토 대상")
        lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 내구 검수 큐(EOS-58 codex 상환) — JSONL 저장소 계층 + 누적 렌더 뷰
# ══════════════════════════════════════════════════════════════════════════
class ReviewQueueEntry(BaseModel):
    """내구 검수 큐 행 — 비수용 outcome 1건의 영속 계약(후보 본문 동반·append-only).

    `candidate_payload`는 **코퍼스 레코드와 동일 직렬화**(JSONL 코퍼스 1행 형태)다 — 검수자가
    문항·정답·해설·검산 조건을 행만으로 보고(P1-1), 수용 판정 시 그 형태 그대로 승격 후보가
    된다(해석 가능한 내구 참조 — 별도 조회 불요). 생성 실패처럼 후보가 없으면 None(정직 —
    없는 본문을 지어내지 않고 `reasons`가 실패 사유를 말한다).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str = Field(
        description="outcome 상태(needs_review·rejected_gate·rejected_duplicate·generation_failed)."
    )
    slug: str | None = Field(
        default=None, description="후보 문제 slug(생성 실패 등 후보 없음이면 None)."
    )
    equivalence_score: float | None = Field(
        default=None, description="게이트 동등성 가중 점수 0~1(판정 없음이면 None)."
    )
    reasons: list[str] = Field(
        default_factory=list, description="거부/검수/실패 사유 누적(조용한 실패 금지)."
    )
    candidate_payload: dict[str, Any] | None = Field(
        default=None,
        description="후보 전문 — 코퍼스 레코드 JSON(자체생성물·저작권 무관). 후보 없으면 None.",
    )
    payload_sha256: str | None = Field(
        default=None,
        description="payload canonical(sha256) — 뷰의 재출현 묶기 키(payload 없으면 None).",
    )
    run_id: str = Field(description="이 행을 만든 축적 회차 식별자(리포트 run_id와 조인).")
    spec_id: str | None = Field(
        default=None,
        description=(
            "이 시도가 쓴 spec 식별자(EOS-121 선결조건 C). 한 회차가 spec 여러 종을 순환하므로 "
            "행마다 남겨야 '어느 spec이 무엇을 냈는지'가 큐에서도 갈린다. None=미기록(구행·단일 "
            "spec 호출부)."
        ),
    )
    duplicate_detector: str | None = Field(
        default=None,
        description=(
            "중복을 잡은 검출기(EOS-121 선결조건 B) — `structural_signature`·`embedding_near`. "
            "`rejected_duplicate` 행에만 값이 있다."
        ),
    )
    duplicate_origin: str | None = Field(
        default=None,
        description=(
            "중복 상대의 출처(EOS-121 B) — `round`(이번 회차가 방금 만든 것)·`corpus`(기존 "
            "자산)·`mixed`. **`duplicate_detector`가 있는데 이 값이 None이면 미판정**이다 "
            "(출처 좌석 미주입) — 'corpus'로 접지 않는다. 검수자가 행만 보고 '생성 다양성 문제'와 "
            "'dedup 정상 동작'을 가를 수 있게 하는 축이며, 회차가 끝나면 복원 불가라 여기 남긴다."
        ),
    )
    recorded_at: datetime | None = Field(
        default=None,
        description="기록 시각(UTC) — append가 스탬프(JSONL 매체 = 발생 즉시 기록·genlog 동형).",
    )
    source_line: int | None = Field(
        default=None,
        description=(
            "매체 파생 필드 — 큐 JSONL에서의 1-기반 줄 번호. append는 기록하지 않고(파일이 줄 "
            "번호를 자칭하지 않음) 로더가 실제 위치를 주입한다 — 뷰의 '행 참조' 재료."
        ),
    )


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    """payload dict의 결정론 sha256 — 키 순서 무관 canonical 직렬화(재출현 묶기 키).

    `problem_id`는 제외한다 — 조립 인스턴스 식별자(매 조립마다 새 uuid4·실측 2026-08-31:
    동일 대본 재생성 시 유일하게 변하는 키)라 *내용*이 아니다. 포함하면 같은 후보의 재출현이
    회차마다 다른 sha가 되어 묶기 키가 무력화된다. 저장되는 payload 자체는 전문 그대로다
    (승격 형태 보존) — 제외는 이 파생 키 계산에서만이다.
    """
    material = {key: value for key, value in payload.items() if key != "problem_id"}
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_from_outcome(
    outcome: GenerationOutcome,
    *,
    run_id: str,
    candidate_payload: Mapping[str, Any] | None,
    spec_id: str | None = None,
) -> ReviewQueueEntry:
    """비수용 GenerationOutcome 1건 → 내구 큐 행(순수 — 파일 I/O 없음).

    `candidate_payload`는 호출자(조성 루트)가 코퍼스 레코드 직렬화로 만들어 주입한다 — 이
    모듈이 `problem_corpus_batch._record_to_json`을 직접 부르면 순환 import라(그쪽이 본 모듈을
    소비) 직렬화 좌석을 주입으로 둔다. 수용 상태를 넘기면 ValueError(큐 대상 아님 — 조용한
    오적재 금지).
    """
    if outcome.status in _STORED_STATUSES:
        raise ValueError(f"수용 상태({outcome.status})는 검수 큐 대상이 아닙니다 — 비수용만 적재.")
    payload = dict(candidate_payload) if candidate_payload is not None else None
    return ReviewQueueEntry(
        status=outcome.status,
        slug=outcome.candidate.problem.slug if outcome.candidate is not None else None,
        equivalence_score=(
            outcome.acceptance.equivalence_score if outcome.acceptance is not None else None
        ),
        reasons=list(outcome.reasons),
        candidate_payload=payload,
        payload_sha256=_canonical_payload_sha256(payload) if payload is not None else None,
        run_id=run_id,
        spec_id=spec_id,
        # 중복 출처 2축(EOS-121 B)은 outcome에서 **그대로** 옮긴다 — 여기서 다시 판정하면
        # 두 벌 산식이 되고, 그 둘이 갈리는 날 어느 쪽이 정본인지 아무도 모른다.
        duplicate_detector=outcome.duplicate_detector,
        duplicate_origin=outcome.duplicate_origin,
    )


def append_review_queue_jsonl(path: Path, entry: ReviewQueueEntry) -> ReviewQueueEntry:
    """큐 행 1건을 JSONL에 **즉시** append한다(호출마다 open→기록→flush→close — genlog 동형).

    `recorded_at`이 비어 있으면 append 시각(UTC)으로 스탬프한다. 매체 파생 필드
    `source_line`은 기록하지 않는다(로더가 실제 줄 번호를 주입). 스탬프된 행을 반환한다.

    실패 경로(2026-08-22 규칙 ① — P2 상환): 배치 종료 일괄 저장이 아니라 **행마다 flush**라,
    장기 라이브 배치가 도중에 죽어도 그때까지의 비수용 기록은 파일에 남는다.
    """
    stamped = (
        entry
        if entry.recorded_at is not None
        else entry.model_copy(update={"recorded_at": datetime.now(UTC)})
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(stamped.model_dump_json(exclude={"source_line"}) + "\n")
        fh.flush()
    return stamped


def load_review_queue_jsonl(path: Path) -> tuple[list[ReviewQueueEntry], list[str]]:
    """큐 JSONL을 읽는다 — (유효 행[줄 번호 주입], 실패 사유[타입명+줄 번호]) 튜플.

    파싱·검증 실패 줄은 삼키지 않고 사유로 수집한다(침묵 실패 금지 — **예외 타입명** + 줄
    번호 + 실패 필드 위치만. 필드 *값*·원문 줄은 넣지 않는다 — `load_generation_logs_jsonl`
    동형). 유효 행에는 실제 1-기반 줄 번호를 `source_line`으로 주입한다(뷰의 행 참조 재료).
    파일 부재는 FileNotFoundError 전파 — "파일 없음"과 "행 0건"은 다르다(미측정≠0).
    """
    entries: list[ReviewQueueEntry] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = ReviewQueueEntry.model_validate(json.loads(text))
            except ValidationError as exc:
                locs = ",".join(
                    "/".join(str(part) for part in err.get("loc", ())) or "(root)"
                    for err in exc.errors()
                )
                errors.append(f"line {line_no}: ValidationError: fields=[{locs}]")
            except Exception as exc:  # noqa: BLE001 — 사유 수집(타입명 보존)이 목적
                errors.append(f"line {line_no}: {type(exc).__name__}")
            else:
                entries.append(parsed.model_copy(update={"source_line": line_no}))
    return entries, errors


def _group_key(entry: ReviewQueueEntry) -> tuple[object, ...]:
    """뷰 묶기 키 — payload sha(재출현 동일 후보). payload 없는 행은 (상태, 사유)로 묶는다."""
    if entry.payload_sha256 is not None:
        return ("payload", entry.payload_sha256)
    return ("nopayload", entry.status, tuple(entry.reasons))


def _payload_summary_lines(payload: Mapping[str, Any]) -> list[str]:
    """후보 payload → 검수자용 본문 요약 줄(문항·정답·해설·검산 조건).

    전문(개행 포함 원문)은 큐 JSONL 행이 정본이다 — 뷰는 md 구조 보존을 위해 개행을
    ' / '로 접은 요약만 싣는다(내용 불변·표시만 1줄화).
    """

    def _fold(value: object) -> str:
        text = value if isinstance(value, str) else str(value)
        return " / ".join(part for part in text.splitlines() if part)

    lines: list[str] = []
    question = payload.get("question_text")
    if isinstance(question, str) and question:
        lines.append(f"- 문항: {_fold(question)}")
    answer = payload.get("answer")
    if isinstance(answer, str) and answer:
        lines.append(f"- 정답: {_fold(answer)}")
    explanation = payload.get("answer_explanation")
    if isinstance(explanation, str) and explanation:
        lines.append(f"- 해설: {_fold(explanation)}")
    verify = payload.get("verify")
    if isinstance(verify, Mapping):
        conditions = verify.get("conditions")
        selection = verify.get("answer_selection")
        if conditions is not None:
            sel_note = f" (selection: {selection})" if isinstance(selection, str) else ""
            lines.append(f"- 검산 조건: {_fold(conditions)}{sel_note}")
    return lines


def render_review_queue_markdown(
    entries: Sequence[ReviewQueueEntry],
    *,
    queue_display_path: str,
    load_errors: Sequence[str] = (),
) -> str:
    """내구 큐 *전체*를 검수자 md로 렌더(순수) — 누적 뷰·재출현 묶음·본문 동반(P1-1/P1-2).

    같은 후보(payload sha 동일)의 재출현은 한 항목으로 묶고 출현 횟수·행 참조를 표기한다 —
    상태·점수·사유는 **최신 행** 기준이다(dedup 판정 등은 코퍼스 상태에 따라 회차마다 다를
    수 있어 최신이 현재 상태다). 로드 실패 행은 헤더에 사유로 노출한다(조용히 사라지지 않음).
    """
    ordered_groups: dict[tuple[object, ...], list[ReviewQueueEntry]] = {}
    for entry in entries:
        ordered_groups.setdefault(_group_key(entry), []).append(entry)

    # 묶음 대표 = 최신 행(파일 뒤쪽) — 정렬은 구뷰와 동일 축(우선순위·점수 내림·slug).
    groups = sorted(
        ordered_groups.values(),
        key=lambda rows: (
            _STATUS_PRIORITY.get(rows[-1].status, len(_STATUS_PRIORITY)),
            -(rows[-1].equivalence_score or 0.0),
            rows[-1].slug or "",
        ),
    )

    status_counts: dict[str, int] = {}
    for rows in groups:
        latest = rows[-1]
        status_counts[latest.status] = status_counts.get(latest.status, 0) + 1

    lines: list[str] = [
        "# S2 검수 큐 워크리스트 — 비수용 후보(누적)",
        "",
        f"- 큐 저장소: {queue_display_path} — 누적 행 {len(entries)} · 항목(묶음) {len(groups)}"
        f" · 로드 실패 {len(load_errors)}",
        f"- 상태별(묶음): 검수필요 {status_counts.get('needs_review', 0)} · "
        f"게이트거부 {status_counts.get('rejected_gate', 0)} · "
        f"과유사거부 {status_counts.get('rejected_duplicate', 0)} · "
        f"생성실패 {status_counts.get('generation_failed', 0)}",
        "- 규약: 기계 사유만 모으고 판정하지 않는다 — needs_review는 사람 판단 체크박스로 결선.",
        "- 별항: 해결 상태 추적·review_status 각인·승격 집행은 범위 밖(OPS-24·승격 태스크 소관)"
        " — 이 파일은 큐 저장소의 렌더 뷰다(정본은 JSONL 행).",
        "",
    ]
    for error in load_errors:
        lines.append(f"- ⚠ 로드 실패 행: {error}")
    if load_errors:
        lines.append("")

    for idx, rows in enumerate(groups, start=1):
        latest = rows[-1]
        score = "—" if latest.equivalence_score is None else f"{latest.equivalence_score:.4f}"
        slug = latest.slug or "(slug 없음)"
        recorded = latest.recorded_at.isoformat() if latest.recorded_at is not None else "—"
        refs = ", ".join(
            f"#{row.source_line}" if row.source_line is not None else "#?" for row in rows
        )
        run_ids = " · ".join(dict.fromkeys(row.run_id for row in rows))  # 중복 제거·순서 보존
        lines.append(f"## {idx}. [{latest.status}] {slug} · 출현 {len(rows)}회")
        lines.append(f"- 동등성 점수: {score} · 최근 기록: {recorded} · run: {run_ids}")
        lines.append(f"- 행 참조: {refs}")
        if latest.candidate_payload is not None:
            lines.extend(_payload_summary_lines(latest.candidate_payload))
        else:
            lines.append("- 본문: (payload 없음 — 후보 미조립·사유만 기록)")
        if latest.reasons:
            lines.append("- 기계 사유:")
            lines.extend(f"  - {reason}" for reason in latest.reasons)
        else:
            lines.append("- 기계 사유: (없음)")
        if latest.status == "needs_review":
            lines.append("- 사람 판단(검수자 체크):")
            lines.append("  - [ ] 교육적으로 타당한 동등문제인가")
            lines.append("  - [ ] 수용(코퍼스 편입) / [ ] 반려 / [ ] 임계값 재검토 대상")
        lines.append("")
    return "\n".join(lines)
