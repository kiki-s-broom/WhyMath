"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createReviewSession,
  fetchReviewDetail,
  fetchReviewList,
  REVIEW_LIST_STATUSES,
  submitReviewTransition,
  type ReviewDetailResult,
  type ReviewFailure,
  type ReviewListResult,
  type ReviewListStatus,
  type ReviewSessionResult,
  type ReviewTransitionRequest,
  type ReviewTransitionResult,
} from "../_lib/adminReviewApi";
import { clearOperatorToken, readOperatorToken } from "../_lib/adminSession";

import { ReviewQueueDetail } from "./ReviewQueueDetail";
import { ReviewQueueList, statusLabel } from "./ReviewQueueList";
import { describeFailure, FailureBox } from "./ReviewQueueNotice";

import styles from "./ReviewQueue.module.css";

/**
 * 검수 큐 화면 컨테이너 (ADMIN-07).
 *
 * 원칙(CLAUDE.md "표현 ≠ 의미")
 * ----------------------------
 * ① 전이 규칙·판정을 재구현하지 않는다 — 버튼은 서버의 `allowed_actions`만 따른다.
 * ② 낙관적 갱신 금지 — 전이가 끝나면 목록·상세를 **서버에서 다시 읽어** 그 값만 보여 준다.
 * ③ "0건"과 "불러오지 못함"을 같은 화면으로 접지 않는다(상태 유니온 그대로 분기).
 *
 * 토큰은 셸이 이미 받아 탭 저장소에 둔 것을 읽기만 한다(이 화면은 셸의 토큰 게이트 안쪽에서만
 * 마운트된다). 401을 받으면 그 토큰을 지우고 재입력을 유도한다.
 */

const PAGE_SIZE = 20;

const TAB_LABEL_HINT = "검수 상태 선택";

type ListState = { kind: "loading" } | ReviewListResult;
type DetailState = { kind: "idle" } | { kind: "loading" } | ReviewDetailResult;

type Notice =
  | { tone: "info"; text: string }
  | { tone: "failure"; failure: ReviewFailure; what: string }
  | null;

export function ReviewQueue() {
  // undefined = 아직 저장소를 읽지 않음(서버 렌더와 첫 클라 렌더를 같게 유지)
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [authFailed, setAuthFailed] = useState(false);
  const [status, setStatus] = useState<ReviewListStatus>("pending");
  const [offset, setOffset] = useState(0);
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState>({ kind: "idle" });
  const [notice, setNotice] = useState<Notice>(null);

  // 늦게 도착한 낡은 응답이 최신 화면을 덮지 않게 하는 요청 번호
  const listSeq = useRef(0);
  const detailSeq = useRef(0);

  useEffect(() => {
    setToken(readOperatorToken());
  }, []);

  /** 401이면 토큰을 지우고 재입력 유도 상태로 전환한다. */
  const noteResult = useCallback((kind: string) => {
    if (kind === "unauthenticated") {
      clearOperatorToken();
      setAuthFailed(true);
    }
  }, []);

  const loadList = useCallback(async () => {
    if (typeof token !== "string") return;
    const seq = ++listSeq.current;
    const result = await fetchReviewList(token, status, PAGE_SIZE, offset);
    if (seq !== listSeq.current) return;
    noteResult(result.kind);
    setList(result);
  }, [token, status, offset, noteResult]);

  const loadDetail = useCallback(
    async (id: string, keepVisible: boolean) => {
      if (typeof token !== "string") return;
      const seq = ++detailSeq.current;
      // 같은 문항의 재조회는 이전 값을 유지해 입력 중이던 확인 단계가 사라지지 않게 한다.
      setDetail((prev) =>
        keepVisible && prev.kind === "ok" && prev.data.problem_id === id ? prev : { kind: "loading" },
      );
      const result = await fetchReviewDetail(token, id);
      if (seq !== detailSeq.current) return;
      noteResult(result.kind);
      setDetail(result);
    },
    [token, noteResult],
  );

  useEffect(() => {
    setList({ kind: "loading" });
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selectedId === null) {
      detailSeq.current += 1;
      setDetail({ kind: "idle" });
      return;
    }
    void loadDetail(selectedId, false);
  }, [selectedId, loadDetail]);

  // 마지막 항목을 처리해 현재 페이지가 비면(총건수는 남음) 마지막 유효 페이지로 물러난다.
  useEffect(() => {
    if (list.kind !== "ok") return;
    if (list.data.items.length === 0 && list.data.total > 0 && offset > 0) {
      setOffset(Math.floor((list.data.total - 1) / PAGE_SIZE) * PAGE_SIZE);
    }
  }, [list, offset]);

  function selectTab(next: ReviewListStatus) {
    if (next === status) return;
    setStatus(next);
    setOffset(0);
    setSelectedId(null);
    setNotice(null);
  }

  /** 문항을 열어 판정 작업을 시작할 때 서버에 착수(started) 세션을 만든다. */
  async function handleStartSession(): Promise<ReviewSessionResult> {
    if (typeof token !== "string" || selectedId === null) {
      return { kind: "unreachable", reason: "선택된 문항 없음" };
    }
    const result = await createReviewSession(token, selectedId);
    noteResult(result.kind);
    return result;
  }

  async function handleTransition(req: ReviewTransitionRequest): Promise<ReviewTransitionResult> {
    if (typeof token !== "string" || selectedId === null) {
      return { kind: "unreachable", reason: "선택된 문항 없음" };
    }
    const id = selectedId;
    const result = await submitReviewTransition(token, id, req);
    noteResult(result.kind);

    if (result.kind === "ok") {
      setNotice({
        tone: "info",
        text:
          "처리되었습니다 — " + statusLabel(result.data.from_status) + " → " +
          statusLabel(result.data.to_status) + " (감사 기록 " + String(result.data.audit_id) + ")",
      });
    } else if (result.kind === "conflict" && result.code === "invalid_review_session") {
      // 세션이 만료됐거나 이미 쓰였다 — 상세가 새 세션을 만든다. 재시도는 사람이 확인 후 다시 누른다.
      setNotice({
        tone: "info",
        text:
          "검수 세션이 유효하지 않습니다 — " + result.message +
          " 새 검수 세션을 시작했습니다. 준비되면 처리를 다시 선택해 확인을 눌러 주세요.",
      });
    } else if (result.kind === "conflict") {
      setNotice({
        tone: "info",
        text:
          result.code === "stale_status"
            ? "다른 곳에서 상태가 바뀌었습니다 — 최신 상태로 다시 불러왔습니다 (현재 상태: " +
              statusLabel(result.currentStatus) + ")"
            : "허용되지 않는 처리입니다 — " + result.message + " (현재 상태: " +
              statusLabel(result.currentStatus) + ")",
      });
    } else {
      setNotice({ tone: "failure", failure: result, what: "처리" });
    }

    // 표시값은 항상 서버 값 — 성공·충돌·없음이면 낙관적 갱신 없이 다시 읽는다.
    if (result.kind === "ok" || result.kind === "conflict" || result.kind === "not-found") {
      await Promise.all([loadList(), loadDetail(id, true)]);
    }
    return result;
  }

  if (token === undefined) return <p className={styles.muted}>세션 확인 중…</p>;

  if (token === null || authFailed) {
    return (
      <FailureBox
        text={describeFailure({ kind: "unauthenticated" }, "요청")}
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <section className={styles.root}>
      <h2 className={styles.title}>검수 큐</h2>

      <div role="group" aria-label={TAB_LABEL_HINT} className={styles.tabs}>
        {REVIEW_LIST_STATUSES.map((value) => (
          <button
            key={value}
            type="button"
            className={styles.tab}
            aria-pressed={value === status}
            onClick={() => selectTab(value)}
          >
            {statusLabel(value)}
          </button>
        ))}
      </div>

      {/* 처리 결과 알림 — 화면 낭독기가 읽도록 항상 존재하는 live region */}
      <div className={styles.live} role="status" aria-live="polite">
        {notice?.tone === "info" && <p className={styles.infoNotice}>{notice.text}</p>}
        {notice?.tone === "failure" && (
          <FailureBox text={describeFailure(notice.failure, notice.what)} />
        )}
      </div>

      <div className={styles.columns}>
        <div className={styles.listPane}>
          <ListPane
            list={list}
            status={status}
            selectedId={selectedId}
            onSelect={(id) => {
              setNotice(null);
              setSelectedId(id);
            }}
            onPage={setOffset}
            onRetry={() => {
              setList({ kind: "loading" });
              void loadList();
            }}
          />
        </div>
        <div className={styles.detailPane}>
          <DetailPane
            detail={detail}
            onTransition={handleTransition}
            onStartSession={handleStartSession}
            onRetry={() => selectedId !== null && void loadDetail(selectedId, false)}
          />
        </div>
      </div>
    </section>
  );
}

function ListPane(props: {
  list: ListState;
  status: ReviewListStatus;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPage: (offset: number) => void;
  onRetry: () => void;
}) {
  const { list } = props;
  if (list.kind === "loading") return <p className={styles.muted}>목록을 불러오는 중…</p>;
  if (list.kind === "empty") {
    // 서버가 200으로 "0건"이라고 답한 경우만 여기 온다 — 실패와 문구·모양을 다르게 한다.
    return (
      <p className={styles.emptyBox}>
        {statusLabel(props.status)} 상태의 문항이 없습니다(서버 응답: 0건).
      </p>
    );
  }
  if (list.kind !== "ok") {
    return <FailureBox text={describeFailure(list, "목록")} onRetry={props.onRetry} />;
  }
  return (
    <ReviewQueueList
      list={list.data}
      selectedId={props.selectedId}
      disabled={false}
      onSelect={props.onSelect}
      onPage={props.onPage}
    />
  );
}

function DetailPane(props: {
  detail: DetailState;
  onTransition: (req: ReviewTransitionRequest) => Promise<ReviewTransitionResult>;
  onStartSession: () => Promise<ReviewSessionResult>;
  onRetry: () => void;
}) {
  const { detail } = props;
  if (detail.kind === "idle") return <p className={styles.muted}>목록에서 문항을 선택하세요.</p>;
  if (detail.kind === "loading") return <p className={styles.muted}>상세를 불러오는 중…</p>;
  if (detail.kind !== "ok") {
    return <FailureBox text={describeFailure(detail, "상세")} onRetry={props.onRetry} />;
  }
  return (
    <ReviewQueueDetail
      key={detail.data.problem_id}
      detail={detail.data}
      onTransition={props.onTransition}
      onStartSession={props.onStartSession}
    />
  );
}
