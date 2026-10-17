import type { ReviewFailure } from "../_lib/adminReviewApi";

import styles from "./ReviewQueue.module.css";

/** 실패 유니온 → 사람 말. 판정은 전부 서버·`adminReviewApi`가 끝냈고 여기서는 번역만 한다. */
export interface FailureText {
  title: string;
  detail: string;
  action: string;
}

/** `what`은 "목록"·"상세"·"처리"처럼 무엇을 하다 실패했는지(문구에 끼워 넣는다). */
export function describeFailure(failure: ReviewFailure, what: string): FailureText {
  switch (failure.kind) {
    case "no-api-base":
      return {
        title: "백엔드 주소가 이 빌드에 없습니다",
        detail: "API 주소가 빌드에 박히지 않아 " + what + " 요청을 보내지 않았습니다.",
        action: "NEXT_PUBLIC_WHYMATH_API_BASE_URL 을 지정해 admin 빌드를 다시 만드세요.",
      };
    case "unreachable":
      return {
        title: "백엔드에 닿지 못했습니다",
        detail:
          what + " 요청이 응답을 받지 못했습니다(실패 종류: " + failure.reason + "). CORS 차단·" +
          "네트워크 단절·시간 초과가 모두 여기에 나타납니다.",
        action: "WHYMATH_CORS_ALLOWED_ORIGINS 에 이 콘솔 origin이 있는지, API가 살아 있는지 확인하세요.",
      };
    case "unauthenticated":
      return {
        title: "토큰이 유효하지 않습니다 (401)",
        detail: "만료됐거나 이 백엔드가 발급한 토큰이 아닙니다.",
        action: "새 액세스 토큰을 다시 입력하세요.",
      };
    case "forbidden":
      return {
        title: "이 계정에는 권한이 없습니다 (403)",
        detail: failure.detail.length > 0 ? "서버 사유: " + failure.detail : "서버가 사유를 주지 않았습니다.",
        action: "검수 권한이 있는 운영자 계정으로 로그인하세요.",
      };
    case "not-found":
      return {
        title: "항목을 찾을 수 없습니다 (404)",
        detail: "이미 삭제됐거나 존재하지 않는 문항입니다.",
        action: "목록을 새로 불러와 확인하세요.",
      };
    case "validation":
      return {
        title: "요청 값이 거부되었습니다 (422)",
        detail: failure.detail.length > 0 ? "서버 사유: " + failure.detail : "입력값을 서버가 받아들이지 않았습니다.",
        action: "입력(사유 등)을 확인한 뒤 다시 시도하세요.",
      };
    case "http-error":
      return {
        title: "백엔드가 오류를 돌려줬습니다 (HTTP " + String(failure.status) + ")",
        detail: what + " 요청이 실패했습니다.",
        action: "잠시 뒤 다시 시도하고, 계속되면 백엔드 로그를 확인하세요.",
      };
    case "malformed":
      return {
        title: "응답을 해석하지 못했습니다",
        detail: "사유: " + failure.reason,
        action: "프런트와 백엔드의 검수 큐 계약이 어긋났을 수 있습니다.",
      };
  }
}

/** 실패 박스. 오류는 `role="alert"`로 즉시 읽힌다. */
export function FailureBox({ text, onRetry }: { text: FailureText; onRetry?: () => void }) {
  return (
    <div className={styles.failure} role="alert">
      <p className={styles.failureTitle}>{text.title}</p>
      <p className={styles.failureText}>{text.detail}</p>
      <p className={styles.failureText}>{text.action}</p>
      {onRetry !== undefined && (
        <button className={styles.secondaryButton} type="button" onClick={onRetry}>
          다시 불러오기
        </button>
      )}
    </div>
  );
}
