"use client";

import { useEffect, useRef, useState } from "react";

import type {
  ReviewAction,
  ReviewDetail,
  ReviewFailure,
  ReviewSessionResult,
  ReviewTransitionRequest,
  ReviewTransitionResult,
} from "../_lib/adminReviewApi";
import { REVIEW_FAILURE_CODES, type ReviewFailureCode } from "../_lib/reviewFailureCodes";

import { formatTime, show, statusLabel } from "./ReviewQueueList";
import { describeFailure } from "./ReviewQueueNotice";

import styles from "./ReviewQueue.module.css";

/** 액션 라벨·확인 문구 — 표현만. 어떤 액션이 *가능한지*는 서버의 `allowed_actions`가 정한다. */
const ACTION_LABEL: Record<ReviewAction, string> = {
  approve: "승인",
  reject: "반려",
  quarantine: "격리",
  release: "격리 해제",
};

const REASON_MAX = 2000;

/** 세션 없이는 제출할 수 없는 액션(서버 계약). 격리·해제는 세션 없이도 제출 가능하다. */
const SESSION_REQUIRED: readonly ReviewAction[] = ["approve", "reject"];

/**
 * 검수 세션 상태.
 *   none     — 아직 만들지 않음(만들 필요가 있으면 곧 creating으로 넘어간다)
 *   creating — 서버에 착수 세션 생성 요청 중
 *   ready    — 서버가 준 세션 id 보유(승인·반려 가능)
 *   failed   — 생성 실패(승인·반려 버튼 비활성 + 이유 표시 + 다시 시도)
 */
type SessionState =
  | { kind: "none" }
  | { kind: "creating" }
  | { kind: "ready"; id: string }
  | { kind: "failed"; failure: ReviewFailure };

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
  /** 전이 요청. 결과 알림·재조회는 부모가 한다(여기서는 제출 중 상태·세션 수명만 관리). */
  onTransition: (req: ReviewTransitionRequest) => Promise<ReviewTransitionResult>;
  /** 착수 세션 생성 — 서버가 시작 시각을 기록한다. 경과 시간은 서버가 계산한다. */
  onStartSession: () => Promise<ReviewSessionResult>;
}

export function ReviewQueueDetail({ detail, onTransition, onStartSession }: Props) {
  const [pending, setPending] = useState<ReviewAction | null>(null);
  const [reason, setReason] = useState("");
  const [failureCode, setFailureCode] = useState<ReviewFailureCode | null>(null);
  const [session, setSession] = useState<SessionState>({ kind: "none" });
  const sessionSeq = useRef(0);
  const [submitting, setSubmitting] = useState(false);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement | null>(null);

  // 확인 단계가 열리면 키보드 사용자가 바로 이어서 조작하도록 포커스를 옮긴다.
  useEffect(() => {
    if (pending === null) return;
    if (pending === "quarantine") reasonRef.current?.focus();
    else confirmRef.current?.focus();
  }, [pending]);

  // 서버가 승인·반려를 허용한 문항만 세션이 필요하다(allowed_actions는 서버 값 그대로).
  const needsSession = detail.allowed_actions.some((a) => SESSION_REQUIRED.includes(a));

  // 문항을 열어 판정 작업을 시작하는 시점에 착수 세션을 만든다. 'none'일 때만 만들므로
  // 재조회(같은 문항 유지)로는 세션이 늘지 않는다. 낡은 응답은 seq로 버린다.
  useEffect(() => {
    if (!needsSession || session.kind !== "none") return;
    const seq = ++sessionSeq.current;
    setSession({ kind: "creating" });
    void onStartSession().then((result) => {
      if (seq !== sessionSeq.current) return;
      setSession(
        result.kind === "ok"
          ? { kind: "ready", id: result.data.review_session_id }
          : { kind: "failed", failure: result },
      );
    });
  }, [needsSession, session.kind, onStartSession]);

  const sessionReady = session.kind === "ready";
  const needsReason = pending === "quarantine";
  const needsFailureCode = pending === "reject";
  const trimmed = reason.trim();
  const sessionBlocked = pending !== null && SESSION_REQUIRED.includes(pending) && !sessionReady;
  // 사유·반려코드 *필수 여부*와 세션 보유만 입력 위생으로 막는다. 최종 판정은 서버가 한다.
  const confirmDisabled =
    submitting ||
    sessionBlocked ||
    (needsReason && trimmed.length === 0) ||
    (needsFailureCode && failureCode === null);

  async function confirm() {
    if (pending === null || confirmDisabled) return;
    setSubmitting(true);
    try {
      // `expected_status`는 사용자가 화면에서 본 상태 그대로다. 세션이 있으면 격리·해제에도 싣는다.
      const result = await onTransition({
        action: pending,
        expectedStatus: detail.review_status,
        reason: needsReason ? trimmed : null,
        failureCode: needsFailureCode ? failureCode : null,
        sessionId: session.kind === "ready" ? session.id : null,
      });
      // 판정이 끝났거나 세션이 무효라고 서버가 답했으면 그 세션은 다시 쓰지 않는다 — 새로 만든다.
      // (그 외 실패·충돌은 세션이 살아 있다고 보고 유지한다. 서버가 소진했다면 다음 제출이
      //  invalid_review_session으로 돌아와 이 분기로 온다.)
      if (result.kind === "ok" || (result.kind === "conflict" && result.code === "invalid_review_session")) {
        sessionSeq.current += 1;
        setSession({ kind: "none" });
      }
    } finally {
      setSubmitting(false);
      setPending(null);
      setReason("");
      setFailureCode(null);
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
                disabled={submitting || (SESSION_REQUIRED.includes(action) && !sessionReady)}
                aria-pressed={pending === action}
                onClick={() => {
                  setPending(action);
                  setReason("");
                  setFailureCode(null);
                }}
              >
                {ACTION_LABEL[action]}
              </button>
            ))}
          </div>
        )}

        {needsSession && session.kind === "creating" && (
          <p className={styles.muted} role="status" data-testid="session-status">
            검수 세션을 시작하는 중… 승인·반려는 세션이 준비된 뒤에 선택할 수 있습니다.
          </p>
        )}
        {needsSession && session.kind === "failed" && (
          <div className={styles.failure} role="alert" data-testid="session-failed">
            <p className={styles.failureTitle}>검수 세션을 시작하지 못해 승인·반려를 쓸 수 없습니다</p>
            <p className={styles.failureText}>{describeFailure(session.failure, "세션 시작").title}</p>
            <p className={styles.failureText}>{describeFailure(session.failure, "세션 시작").detail}</p>
            <p className={styles.failureText}>{describeFailure(session.failure, "세션 시작").action}</p>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => setSession({ kind: "none" })}
            >
              세션 다시 만들기
            </button>
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
            {needsFailureCode && (
              <fieldset className={styles.codeGroup} disabled={submitting}>
                <legend className={styles.label}>반려 코드 (필수 — 하나를 선택하세요)</legend>
                {REVIEW_FAILURE_CODES.map((entry) => (
                  <label key={entry.code} className={styles.codeOption}>
                    <input
                      type="radio"
                      name="wm-review-failure-code"
                      value={entry.code}
                      checked={failureCode === entry.code}
                      onChange={() => setFailureCode(entry.code)}
                    />
                    <span>
                      <strong>{entry.code}</strong> {entry.label}
                      <span className={styles.muted}> — {entry.detail}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
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
                  setFailureCode(null);
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
