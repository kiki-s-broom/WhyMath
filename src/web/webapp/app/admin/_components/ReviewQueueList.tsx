import type { ReviewList, ReviewListItem } from "../_lib/adminReviewApi";

import styles from "./ReviewQueue.module.css";

/** 상태 코드 → 표시 라벨. 모르는 값은 서버 문자열 그대로(숨기지 않는다). */
export function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "검수 대기";
    case "approved":
      return "승인됨";
    case "rejected":
      return "반려됨";
    case "quarantined":
      return "격리됨";
    default:
      return status;
  }
}

/** 서버 값 표시 전용 — null은 "-"로만 바꾸고 숫자는 가공하지 않는다. */
export function show(value: string | number | null): string {
  return value === null ? "-" : String(value);
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ko-KR");
}

interface Props {
  list: ReviewList;
  selectedId: string | null;
  disabled: boolean;
  onSelect: (id: string) => void;
  onPage: (offset: number) => void;
}

function Row({ item, selected, onSelect }: { item: ReviewListItem; selected: boolean; onSelect: () => void }) {
  return (
    <tr className={selected ? styles.rowSelected : undefined}>
      <th scope="row" className={styles.idCell}>
        <button
          className={styles.rowButton}
          type="button"
          aria-current={selected ? "true" : undefined}
          onClick={onSelect}
        >
          {item.problem_id.slice(0, 8)}
          <span className={styles.srOnly}> 문항 {item.problem_id} 상세 열기</span>
        </button>
      </th>
      <td>{statusLabel(item.review_status)}</td>
      <td>{show(item.subject)}</td>
      <td>{show(item.domain)}</td>
      <td className={styles.num}>{show(item.difficulty_overall)}</td>
      <td>{show(item.source_type)}</td>
      <td className={styles.num}>{show(item.review_score)}</td>
      <td>{formatTime(item.created_at)}</td>
    </tr>
  );
}

/** 목록 표 + 페이지 이동. 페이지 계산은 표시용 산술뿐이고 총건수·offset은 서버 값이다. */
export function ReviewQueueList({ list, selectedId, disabled, onSelect, onPage }: Props) {
  const from = list.total === 0 ? 0 : list.offset + 1;
  const to = list.offset + list.items.length;
  const hasPrev = list.offset > 0;
  const hasNext = list.offset + list.limit < list.total;
  return (
    <div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>검수 대상 문항 목록</caption>
          <thead>
            <tr>
              <th scope="col">문항</th>
              <th scope="col">상태</th>
              <th scope="col">과목</th>
              <th scope="col">영역</th>
              <th scope="col">난이도</th>
              <th scope="col">출처</th>
              <th scope="col">점수</th>
              <th scope="col">생성</th>
            </tr>
          </thead>
          <tbody>
            {list.items.map((item) => (
              <Row
                key={item.problem_id}
                item={item}
                selected={item.problem_id === selectedId}
                onSelect={() => onSelect(item.problem_id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <nav className={styles.pager} aria-label="목록 페이지">
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={disabled || !hasPrev}
          onClick={() => onPage(Math.max(0, list.offset - list.limit))}
        >
          이전
        </button>
        <span>
          전체 {list.total}건 중 {from}–{to}
        </span>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={disabled || !hasNext}
          onClick={() => onPage(list.offset + list.limit)}
        >
          다음
        </button>
      </nav>
    </div>
  );
}
