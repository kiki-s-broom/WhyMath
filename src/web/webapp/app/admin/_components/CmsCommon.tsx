"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { CmsFailure } from "../_lib/adminCmsApi";
import { clearOperatorToken, readOperatorToken } from "../_lib/adminSession";

import styles from "./Cms.module.css";

/**
 * CMS 화면 공통 부품 — 실패 문구·토큰 게이트·표시 도우미.
 *
 * 판정은 전부 서버·`adminCmsApi`가 끝냈고 여기서는 **번역과 표시**만 한다(표현 ≠ 의미).
 */

export interface FailureText {
  title: string;
  detail: string;
  action: string;
}

/** 서버 사유(문구·필드·부가 목록)를 한 줄로 이어 붙인다. 비면 빈 문자열. */
function problemLine(problem: { message: string; field: string | null; details: string[] }): string {
  const parts: string[] = [];
  if (problem.message.length > 0) parts.push(problem.message);
  if (problem.field !== null) parts.push("(필드: " + problem.field + ")");
  if (problem.details.length > 0) parts.push("[" + problem.details.join(", ") + "]");
  return parts.join(" ");
}

/** 409 사유 코드별로 운영자가 다음에 할 일(서버 `code` 기준 — 문구가 아니라 식별자로 분기한다). */
const CONFLICT_ACTION: Record<string, string> = {
  file_owned: "원천 파일(graph.json)에서 고친 뒤 다시 적재해야 합니다. 이 화면에서는 지울 수 없습니다.",
  has_published_version: "발행본을 먼저 폐기(deprecate)한 뒤 다시 시도하세요.",
  has_edges: "이 개념에 연결된 관계를 먼저 지운 뒤 다시 시도하세요.",
  has_children: "하위 개념을 먼저 정리한 뒤 다시 시도하세요.",
  referenced: "학습 기록·문항 연결 등이 이 개념을 쓰고 있어 지울 수 없습니다.",
  edge_exists: "이미 같은 선수 관계가 있습니다. 목록을 새로 불러와 확인하세요.",
  code_taken: "이미 쓰이고 있는 개념 코드입니다. 다른 코드를 입력하세요.",
  concept_exists: "이미 개념으로 발행된 코드라 제안을 수정할 수 없습니다. 개념 편집에서 새 초안을 만드세요.",
};

/** `what`은 "목록"·"저장"·"발행"처럼 무엇을 하다 실패했는지(문구에 끼워 넣는다). */
export function describeCmsFailure(failure: CmsFailure, what: string): FailureText {
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
    case "forbidden": {
      const line = problemLine(failure.problem);
      return {
        title: "이 작업에 필요한 권한이 없습니다 (403)",
        detail:
          what + " 요청을 서버가 거부했습니다." + (line.length > 0 ? " 서버 사유: " + line : ""),
        action: "이 작업(편집·검수·발행)의 권한이 있는 운영자 계정으로 로그인하세요.",
      };
    }
    case "not-found":
      return {
        title: "항목을 찾을 수 없습니다 (404)",
        detail: "이미 삭제됐거나 존재하지 않는 항목입니다.",
        action: "목록을 새로 불러와 확인하세요.",
      };
    case "conflict": {
      const line = problemLine(failure.problem);
      const stale =
        failure.problem.code === "stale_status" || failure.problem.code === "stale_pointer";
      return {
        title: "현재 상태와 맞지 않는 요청입니다 (409)",
        detail:
          (line.length > 0 ? "서버 사유: " + line : what + " 요청이 현재 상태와 충돌했습니다.") +
          (failure.problem.currentStatus !== null ? " 현재 상태: " + failure.problem.currentStatus : ""),
        action: stale
          ? "다른 곳에서 먼저 바뀌었습니다. 최신 상태로 다시 불러온 뒤 다시 시도하세요."
          : CONFLICT_ACTION[failure.problem.code] ?? "표시된 사유를 해소한 뒤 다시 시도하세요.",
      };
    }
    case "validation": {
      const line = problemLine(failure.problem);
      if (failure.problem.code === "prerequisite_cycle") {
        // 순환 경로는 서버가 준 개념 코드 배열을 화살표로 이어 그대로 보인다(판정은 서버가 했다).
        const route = failure.problem.path.length > 0 ? failure.problem.path.join(" → ") : line;
        return {
          title: "선수 관계가 고리처럼 이어져 추가할 수 없습니다 (422)",
          detail:
            "이 관계를 더하면 아래처럼 한 바퀴를 돌아 자기 자신으로 돌아옵니다" +
            (route.length > 0 ? ": " + route : "."),
          action:
            "고리 중 한 곳의 관계를 먼저 지우거나, 선수와 후행의 방향을 바꿔서 다시 시도하세요.",
        };
      }
      return {
        title: "요청 값이 거부되었습니다 (422)",
        detail: line.length > 0 ? "서버 사유: " + line : "입력값을 서버가 받아들이지 않았습니다.",
        action: "입력을 확인한 뒤 다시 시도하세요.",
      };
    }
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
        action: "프런트와 백엔드의 CMS 계약이 어긋났을 수 있습니다.",
      };
  }
}

/** 실패 박스. 오류는 `role="alert"`로 즉시 읽힌다. */
export function CmsFailureBox({ text, onRetry }: { text: FailureText; onRetry?: () => void }) {
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

/** 처리 결과 알림 — 성공·안내(info)와 실패(failure)를 한 자리(live region)에서 보인다. */
export type CmsNotice =
  | { tone: "info"; text: string }
  | { tone: "failure"; failure: CmsFailure; what: string }
  | null;

export function CmsNoticeView({ notice }: { notice: CmsNotice }) {
  return (
    <div className={styles.live} role="status" aria-live="polite">
      {notice?.tone === "info" && <p className={styles.infoNotice}>{notice.text}</p>}
      {notice?.tone === "failure" && (
        <CmsFailureBox text={describeCmsFailure(notice.failure, notice.what)} />
      )}
    </div>
  );
}

/** 세션 확인 결과를 하위 화면에 넘기는 함수 모양: 401이면 토큰을 지우고 재입력을 유도한다. */
export type NoteResult = (kind: string) => void;

/**
 * 토큰 게이트. 토큰은 셸이 이미 받아 탭 저장소에 둔 것을 읽기만 한다(이 화면은 셸의 토큰 게이트
 * 안쪽에서만 마운트된다). 401을 받으면 그 토큰을 지우고 재입력을 유도한다.
 */
export function CmsSessionGate({
  children,
}: {
  children: (token: string, note: NoteResult) => ReactNode;
}) {
  // undefined = 아직 저장소를 읽지 않음(서버 렌더와 첫 클라 렌더를 같게 유지)
  const [token, setToken] = useState<string | null | undefined>(undefined);
  const [authFailed, setAuthFailed] = useState(false);

  useEffect(() => {
    setToken(readOperatorToken());
  }, []);

  const note = useCallback<NoteResult>((kind) => {
    if (kind === "unauthenticated") {
      clearOperatorToken();
      setAuthFailed(true);
    }
  }, []);

  if (token === undefined) return <p className={styles.muted}>세션 확인 중…</p>;
  if (token === null || authFailed) {
    return (
      <CmsFailureBox
        text={describeCmsFailure({ kind: "unauthenticated" }, "요청")}
        onRetry={() => window.location.reload()}
      />
    );
  }
  return <>{children(token, note)}</>;
}

// ── 표시 도우미 ──────────────────────────────────────────────────────────

/** 서버 값 표시 전용 — null은 "-"로만 바꾸고 값은 가공하지 않는다. 객체는 JSON 문자열. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function formatTime(iso: string | null): string {
  if (iso === null) return "-";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ko-KR");
}

/** 긴 식별자(UUID)를 목록·표에서 짧게 보이게 한다. 원문은 `title`/상세에 남긴다. */
export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

// ── 판 상태·전이 라벨 (표시 전용) ────────────────────────────────────────
//
// 판 이력 화면과 신규 개념 제안 목록이 같은 사전을 쓰도록 한 자리에 둔다. 모르는 값은 서버 문자열
// 그대로 보인다(숨기지 않는다). 어떤 전이가 가능한지는 이 사전이 아니라 서버의 `allowed_actions`가 정한다.

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "초안",
  IN_REVIEW: "검토 중",
  IN_QA: "QA 중",
  APPROVED: "승인됨",
  PUBLISHED: "발행됨",
  DEPRECATED: "폐기 예정",
  RETIRED: "은퇴",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

const ACTION_LABEL: Record<string, string> = {
  submit: "검토 제출",
  request_changes: "보완 요청",
  pass_review: "검토 통과",
  fail_qa: "QA 불합격",
  approve: "승인",
  publish: "발행",
  deprecate: "폐기 예정으로 표시",
  retire: "은퇴",
};

export function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}
