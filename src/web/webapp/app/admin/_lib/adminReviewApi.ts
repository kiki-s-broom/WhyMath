/**
 * 검수 큐 BFF 클라이언트 (ADMIN-07) — 검수 큐 화면이 백엔드와 말하는 **유일한 자리**.
 *
 * 경계 (04 §3 · CLAUDE.md "표현 ≠ 의미")
 * -------------------------------------
 * 여기에는 전이 규칙도, 승인 가능 여부 판정도, 점수 계산도 없다. 하는 일은 ①빌드에 박힌 API
 * 주소를 꺼내고 ②Bearer 토큰을 붙여 요청하고 ③응답을 **런타임 검증**해 구분 가능한 결과값으로
 * 바꾸는 것뿐이다. 어떤 버튼을 보일지는 서버가 준 `allowed_actions`가 정하고, 현재 상태가
 * 낡았는지는 서버가 `expected_status`로 판정한다(409).
 *
 * 구조: 네트워크 호출(fetch)은 아래 `request()` **한 곳**뿐이다. 목록·상세·전이가 모두 이 함수를 지나므로
 * 토큰 부착·타임아웃·자격증명 모드·예외 타입명 기록이 세 호출에서 갈라질 수 없다
 * (`tests/infra/test_webapp_admin_review_governance.py`가 동결).
 *
 * 응답 검증: 타입 단언으로 서버를 믿지 않는다. 모양이 틀리면 `malformed`다 — 틀린 응답을
 * 정상 화면으로 렌더하면 검수자가 "없는 값"을 보고 승인하게 된다.
 */

import { apiBaseUrl } from "./adminApi";

/** 10초 타임아웃 — 느린 백엔드에 무한 대기하지 않는다(CLAUDE.md). */
const REQUEST_TIMEOUT_MS = 10_000;

const LIST_PATH = "/v1/admin/review-queue/items";

/** 목록 탭의 4상태. 서버 계약의 `status` 쿼리 값이다. */
export const REVIEW_LIST_STATUSES = ["pending", "approved", "rejected", "quarantined"] as const;
export type ReviewListStatus = (typeof REVIEW_LIST_STATUSES)[number];

/** 전이 액션 4종. 이 목록은 *서버 응답 검증용*이지 전이 규칙이 아니다(규칙은 서버가 안다). */
export const REVIEW_ACTIONS = ["approve", "reject", "quarantine", "release"] as const;
export type ReviewAction = (typeof REVIEW_ACTIONS)[number];

export interface ReviewListItem {
  problem_id: string;
  review_status: string;
  subject: string | null;
  domain: string | null;
  difficulty_overall: number | null;
  source_type: string | null;
  review_score: number | null;
  created_at: string;
}

export interface ReviewList {
  status: string;
  total: number;
  limit: number;
  offset: number;
  items: ReviewListItem[];
}

export interface ReviewDetail {
  problem_id: string;
  review_status: string;
  question_text: string | null;
  choices: unknown[] | null;
  answer: string | null;
  answer_explanation: string | null;
  subject: string | null;
  domain: string | null;
  difficulty_overall: number | null;
  source_type: string | null;
  review_score: number | null;
  quarantine_reason: string | null;
  quarantined_at: string | null;
  created_at: string;
  allowed_actions: ReviewAction[];
}

export interface ReviewTransitionDone {
  problem_id: string;
  from_status: string;
  to_status: string;
  audit_id: string | number;
  occurred_at: string;
}

/** 호출 종류와 무관한 실패. 사유마다 운영자가 해야 할 행동이 달라 합치지 않는다. */
export type ReviewFailure =
  | { kind: "no-api-base" }
  | { kind: "unauthenticated" }
  | { kind: "forbidden"; detail: string }
  | { kind: "not-found" }
  | { kind: "validation"; detail: string }
  | { kind: "http-error"; status: number }
  | { kind: "malformed"; reason: string }
  | { kind: "unreachable"; reason: string };

/** 200인데 0건(`empty`)과 불러오지 못함(실패 유니온)을 타입으로 가른다. */
export type ReviewListResult = { kind: "ok"; data: ReviewList } | { kind: "empty"; data: ReviewList } | ReviewFailure;
export type ReviewDetailResult = { kind: "ok"; data: ReviewDetail } | ReviewFailure;
export type ReviewTransitionResult =
  | { kind: "ok"; data: ReviewTransitionDone }
  | { kind: "conflict"; code: "stale_status" | "illegal_transition"; message: string; currentStatus: string }
  | ReviewFailure;

// ── 런타임 검증 보조 ─────────────────────────────────────────────────────

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStr(value: unknown): value is string {
  return typeof value === "string";
}

function isStrOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNumOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isAction(value: unknown): value is ReviewAction {
  return typeof value === "string" && (REVIEW_ACTIONS as readonly string[]).includes(value);
}

function parseListItem(raw: unknown): ReviewListItem | null {
  if (!isRecord(raw)) return null;
  if (!isStr(raw.problem_id) || !isStr(raw.review_status) || !isStr(raw.created_at)) return null;
  if (!isStrOrNull(raw.subject) || !isStrOrNull(raw.domain) || !isStrOrNull(raw.source_type)) {
    return null;
  }
  if (!isNumOrNull(raw.difficulty_overall) || !isNumOrNull(raw.review_score)) return null;
  return {
    problem_id: raw.problem_id,
    review_status: raw.review_status,
    subject: raw.subject,
    domain: raw.domain,
    difficulty_overall: raw.difficulty_overall,
    source_type: raw.source_type,
    review_score: raw.review_score,
    created_at: raw.created_at,
  };
}

function parseList(raw: unknown): ReviewList | null {
  if (!isRecord(raw) || !Array.isArray(raw.items)) return null;
  if (!isStr(raw.status) || !isInt(raw.total) || !isInt(raw.limit) || !isInt(raw.offset)) {
    return null;
  }
  const items: ReviewListItem[] = [];
  for (const rawItem of raw.items) {
    const item = parseListItem(rawItem);
    if (item === null) return null;
    items.push(item);
  }
  return { status: raw.status, total: raw.total, limit: raw.limit, offset: raw.offset, items };
}

function parseDetail(raw: unknown): ReviewDetail | null {
  if (!isRecord(raw)) return null;
  if (!isStr(raw.problem_id) || !isStr(raw.review_status) || !isStr(raw.created_at)) return null;
  if (
    !isStrOrNull(raw.question_text) ||
    !isStrOrNull(raw.answer) ||
    !isStrOrNull(raw.answer_explanation) ||
    !isStrOrNull(raw.subject) ||
    !isStrOrNull(raw.domain) ||
    !isStrOrNull(raw.source_type) ||
    !isStrOrNull(raw.quarantine_reason) ||
    !isStrOrNull(raw.quarantined_at)
  ) {
    return null;
  }
  if (!isNumOrNull(raw.difficulty_overall) || !isNumOrNull(raw.review_score)) return null;
  if (raw.choices !== null && !Array.isArray(raw.choices)) return null;
  if (!Array.isArray(raw.allowed_actions)) return null;
  const actions: ReviewAction[] = [];
  for (const action of raw.allowed_actions) {
    // 모르는 액션을 조용히 버리면 "버튼이 왜 없지"가 되므로 계약 위반으로 올린다.
    if (!isAction(action)) return null;
    actions.push(action);
  }
  return {
    problem_id: raw.problem_id,
    review_status: raw.review_status,
    question_text: raw.question_text,
    choices: raw.choices,
    answer: raw.answer,
    answer_explanation: raw.answer_explanation,
    subject: raw.subject,
    domain: raw.domain,
    difficulty_overall: raw.difficulty_overall,
    source_type: raw.source_type,
    review_score: raw.review_score,
    quarantine_reason: raw.quarantine_reason,
    quarantined_at: raw.quarantined_at,
    created_at: raw.created_at,
    allowed_actions: actions,
  };
}

function parseTransition(raw: unknown): ReviewTransitionDone | null {
  if (!isRecord(raw)) return null;
  if (!isStr(raw.problem_id) || !isStr(raw.from_status) || !isStr(raw.to_status)) return null;
  if (!isStr(raw.occurred_at)) return null;
  if (!isStr(raw.audit_id) && !isInt(raw.audit_id)) return null;
  return {
    problem_id: raw.problem_id,
    from_status: raw.from_status,
    to_status: raw.to_status,
    audit_id: raw.audit_id,
    occurred_at: raw.occurred_at,
  };
}

/** 409 본문 `{detail:{code,message,current_status}}` → 충돌 결과. 모양이 다르면 null. */
function parseConflict(raw: unknown): Extract<ReviewTransitionResult, { kind: "conflict" }> | null {
  if (!isRecord(raw) || !isRecord(raw.detail)) return null;
  const { code, message, current_status: currentStatus } = raw.detail;
  if (code !== "stale_status" && code !== "illegal_transition") return null;
  if (!isStr(message) || !isStr(currentStatus)) return null;
  return { kind: "conflict", code, message, currentStatus };
}

/** 403·422의 사유 문자열. FastAPI 422는 detail이 배열일 수 있어 문자열이 아니면 빈 값. */
function detailText(payload: unknown): string {
  if (isRecord(payload) && isStr(payload.detail)) return payload.detail;
  return "";
}

// ── 단 하나의 fetch ──────────────────────────────────────────────────────

type RawResult =
  | { tag: "failure"; failure: ReviewFailure }
  | { tag: "response"; status: number; ok: boolean; payload: unknown; parsed: boolean };

/**
 * 모든 호출이 지나는 유일한 `fetch` 지점.
 *
 * 쿠키를 주고받지 않는다(`credentials:"omit"`) — Bearer 헤더만 쓰며, 자격증명 모드를 켜면
 * 서버의 CORS 설정과 어긋나 조용히 차단된다. 예외는 **타입명**만 남긴다(침묵 실패 금지 ·
 * 토큰·본문 값은 기록하지 않는다).
 */
async function request(
  token: string,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<RawResult> {
  const base = apiBaseUrl();
  if (base === null) return { tag: "failure", failure: { kind: "no-api-base" } };

  const headers: Record<string, string> = {
    Authorization: "Bearer " + token,
    Accept: "application/json",
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(base + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    // CORS 차단·DNS·연결 거부·타임아웃이 전부 여기로 온다 — 타입명을 남긴다.
    const name = error instanceof Error ? error.name : typeof error;
    return { tag: "failure", failure: { kind: "unreachable", reason: name } };
  }

  let payload: unknown = undefined;
  let parsed = true;
  try {
    payload = await response.json();
  } catch {
    // 오류 응답은 본문이 JSON이 아닐 수 있다. 2xx에서만 이것이 계약 위반(malformed)이 된다.
    parsed = false;
  }
  return { tag: "response", status: response.status, ok: response.ok, payload, parsed };
}

/** 상태코드 → 공통 실패. 해당 없으면(2xx 또는 호출별 처리 대상) null. */
function commonFailure(raw: RawResult, notFoundIsFailure: boolean): ReviewFailure | null {
  if (raw.tag === "failure") return raw.failure;
  if (raw.status === 401) return { kind: "unauthenticated" };
  if (raw.status === 403) return { kind: "forbidden", detail: detailText(raw.payload) };
  if (raw.status === 404 && notFoundIsFailure) return { kind: "not-found" };
  if (raw.status === 422) return { kind: "validation", detail: detailText(raw.payload) };
  if (!raw.ok && raw.status !== 409) return { kind: "http-error", status: raw.status };
  return null;
}

function malformed(reason: string): ReviewFailure {
  return { kind: "malformed", reason };
}

// ── 공개 호출 3종 ────────────────────────────────────────────────────────

export async function fetchReviewList(
  token: string,
  status: ReviewListStatus,
  limit: number,
  offset: number,
): Promise<ReviewListResult> {
  const query = new URLSearchParams({
    status,
    limit: String(limit),
    offset: String(offset),
  });
  const raw = await request(token, "GET", LIST_PATH + "?" + query.toString());
  const failure = commonFailure(raw, false);
  if (failure !== null) return failure;
  if (raw.tag !== "response") return malformed("내부 상태 오류");
  if (raw.status === 409) return { kind: "http-error", status: 409 };
  if (!raw.parsed) return malformed("JSON 파싱 실패");
  const data = parseList(raw.payload);
  if (data === null) return malformed("목록 응답 구조가 계약과 다름");
  return data.total === 0 && data.items.length === 0 ? { kind: "empty", data } : { kind: "ok", data };
}

export async function fetchReviewDetail(
  token: string,
  problemId: string,
): Promise<ReviewDetailResult> {
  const raw = await request(token, "GET", LIST_PATH + "/" + encodeURIComponent(problemId));
  const failure = commonFailure(raw, true);
  if (failure !== null) return failure;
  if (raw.tag !== "response") return malformed("내부 상태 오류");
  if (raw.status === 409) return { kind: "http-error", status: 409 };
  if (!raw.parsed) return malformed("JSON 파싱 실패");
  const data = parseDetail(raw.payload);
  if (data === null) return malformed("상세 응답 구조가 계약과 다름");
  return { kind: "ok", data };
}

/**
 * 전이 요청. `expectedStatus`는 사용자가 화면에서 **본 상태 그대로** 보낸다 — 낡았는지의
 * 판정(stale)은 서버가 한다. 클라가 "지금도 이 상태겠지"를 추정해 고치지 않는다.
 */
export async function submitReviewTransition(
  token: string,
  problemId: string,
  action: ReviewAction,
  expectedStatus: string,
  reason: string | null,
): Promise<ReviewTransitionResult> {
  const body: { action: ReviewAction; expected_status: string; reason?: string } = {
    action,
    expected_status: expectedStatus,
  };
  if (reason !== null) body.reason = reason;
  const raw = await request(
    token,
    "POST",
    LIST_PATH + "/" + encodeURIComponent(problemId) + "/transitions",
    body,
  );
  const failure = commonFailure(raw, true);
  if (failure !== null) return failure;
  if (raw.tag !== "response") return malformed("내부 상태 오류");
  if (raw.status === 409) {
    const conflict = parseConflict(raw.payload);
    return conflict ?? malformed("409 응답 구조가 계약과 다름");
  }
  if (!raw.parsed) return malformed("JSON 파싱 실패");
  const data = parseTransition(raw.payload);
  if (data === null) return malformed("전이 응답 구조가 계약과 다름");
  return { kind: "ok", data };
}
