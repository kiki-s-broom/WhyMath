"use client";

import { useEffect, useRef, useState } from "react";

import type { ReviewAction, ReviewDetail } from "../_lib/adminReviewApi";

import { formatTime, show, statusLabel } from "./ReviewQueueList";

import styles from "./ReviewQueue.module.css";

/** 액션 라벨·확인 문구 — 표현만. 어떤 액션이 *가능한지*는 서버의 `allowed_actions`가 정한다. */
const ACTION_LABEL: Record<ReviewAction, string> = {
  approve: "승인",
  reject: "반려",
  quarantine: "격리",
  release: "격리 해제",
};

const REASON_MAX = 2000;

/** 선택지·본문은 **텍스트로만** 렌더한다(원문 HTML을 해석하지 않는다 — XSS 방어). */
function choiceText(choice: unknown): string {
  if (typeof choice === "string") return choice;
  if (typeof choice === "number" || typeof choice === "boolean") return String(choice);
  return JSON.stringify(choice);
}

function TextBlock({ title, value }: { title: string; value: string | null }) {
  return (
    <section className={styles.block}>
      <h4 className={styles.blockTitle}>{title}</h4>
      {value === null || value.length === 0 ? (
        <p className={styles.muted}>(없음)</p>
      ) : (
        <pre className={styles.text}>{value}</pre>
      )}
    </section>
  );
}

interface Props {
  detail: ReviewDetail;
  /** 전이 요청. 결과 알림·재조회는 부모가 한다(여기서는 제출 중 상태만 관리). */
  onTransition: (action: ReviewAction, expectedStatus: string, reason: string | null) => Promise<void>;
}

export function ReviewQueueDetail({ detail, onTransition }: Props) {
  const [pending, setPending] = useState<ReviewAction | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement | null>(null);

  // 확인 단계가 열리면 키보드 사용자가 바로 이어서 조작하도록 포커스를 옮긴다.
  useEffect(() => {
    if (pending === null) return;
    if (pending === "quarantine") reasonRef.current?.focus();
    else confirmRef.current?.focus();
  }, [pending]);

  const needsReason = pending === "quarantine";
  const trimmed = reason.trim();
  // 사유 *필수 여부*만 입력 위생으로 막는다. 길이·형식의 최종 판정은 서버(422)가 한다.
  const confirmDisabled = submitting || (needsReason && trimmed.length === 0);

  async function confirm() {
    if (pending === null || confirmDisabled) return;
    setSubmitting(true);
    try {
      // `expected_status`는 사용자가 화면에서 본 상태 그대로다.
      await onTransition(pending, detail.review_status, needsReason ? trimmed : null);
    } finally {
      setSubmitting(false);
      setPending(null);
      setReason("");
    }
  }

  return (
    <article className={styles.detail} aria-labelledby="wm-review-detail-title">
      <h3 id="wm-review-detail-title" className={styles.detailTitle} tabIndex={-1}>
        문항 상세
      </h3>
      <dl className={styles.meta}>
        <dt>문항 ID</dt>
        <dd className={styles.mono}>{detail.problem_id}</dd>
        <dt>상태</dt>
        <dd>{statusLabel(detail.review_status)}</dd>
        <dt>과목 / 영역</dt>
        <dd>
          {show(detail.subject)} / {show(detail.domain)}
        </dd>
        <dt>난이도</dt>
        <dd>{show(detail.difficulty_overall)}</dd>
        <dt>출처</dt>
        <dd>{show(detail.source_type)}</dd>
        <dt>검수 점수</dt>
        <dd>{show(detail.review_score)}</dd>
        <dt>생성</dt>
        <dd>{formatTime(detail.created_at)}</dd>
        {detail.quarantine_reason !== null && (
          <>
            <dt>격리 사유</dt>
            <dd>{detail.quarantine_reason}</dd>
          </>
        )}
        {detail.quarantined_at !== null && (
          <>
            <dt>격리 시각</dt>
            <dd>{formatTime(detail.quarantined_at)}</dd>
          </>
        )}
      </dl>

      <TextBlock title="문항" value={detail.question_text} />
      <section className={styles.block}>
        <h4 className={styles.blockTitle}>선택지</h4>
        {detail.choices === null || detail.choices.length === 0 ? (
          <p className={styles.muted}>(없음)</p>
        ) : (
          <ol className={styles.choices}>
            {detail.choices.map((choice, index) => (
              <li key={index}>
                <pre className={styles.text}>{choiceText(choice)}</pre>
              </li>
            ))}
          </ol>
        )}
      </section>
      <TextBlock title="정답" value={detail.answer} />
      <TextBlock title="해설" value={detail.answer_explanation} />

      <section className={styles.block} aria-label="검수 처리">
        <h4 className={styles.blockTitle}>처리</h4>
        {detail.allowed_actions.length === 0 ? (
          <p className={styles.muted}>이 상태에서 서버가 허용한 처리가 없습니다.</p>
        ) : (
          <div className={styles.actions}>
            {detail.allowed_actions.map((action) => (
              <button
                key={action}
                className={styles.actionButton}
                type="button"
                disabled={submitting}
                aria-pressed={pending === action}
                onClick={() => {
                  setPending(action);
                  setReason("");
                }}
              >
                {ACTION_LABEL[action]}
              </button>
            ))}
          </div>
        )}

        {pending !== null && (
          <div className={styles.confirm} role="group" aria-label={ACTION_LABEL[pending] + " 확인"}>
            <p className={styles.confirmText}>
              이 문항을 <strong>{ACTION_LABEL[pending]}</strong>
              {pending === "release" ? "하시겠습니까?" : " 처리하시겠습니까?"} 현재 상태(
              {statusLabel(detail.review_status)}) 기준으로 요청되며, 그 사이 다른 곳에서 바뀌었으면
              서버가 거부합니다.
            </p>
            {needsReason && (
              <div>
                <label className={styles.label} htmlFor="wm-review-reason">
                  격리 사유 (필수, {REASON_MAX}자 이내)
                </label>
                <textarea
                  id="wm-review-reason"
                  ref={reasonRef}
                  className={styles.textarea}
                  rows={3}
                  maxLength={REASON_MAX}
                  value={reason}
                  disabled={submitting}
                  onChange={(event) => setReason(event.target.value)}
                />
              </div>
            )}
            <div className={styles.actions}>
              <button
                ref={confirmRef}
                className={styles.primaryButton}
                type="button"
                disabled={confirmDisabled}
                onClick={() => void confirm()}
              >
                {submitting ? "처리 중…" : "확인"}
              </button>
              <button
                className={styles.secondaryButton}
                type="button"
                disabled={submitting}
                onClick={() => {
                  setPending(null);
                  setReason("");
                }}
              >
                취소
              </button>
            </div>
          </div>
        )}
      </section>
    </article>
  );
}
