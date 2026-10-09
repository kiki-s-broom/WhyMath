/**
 * CMS BFF 클라이언트 (P3-12) — 콘텐츠 운영 화면이 백엔드와 말하는 **유일한 자리**.
 *
 * 경계 (04 §3 · CLAUDE.md "표현 ≠ 의미")
 * -------------------------------------
 * 여기에는 전이 규칙도, 권한 판정도, 편집 허용 여부 판정도 없다. 하는 일은 ①빌드에 박힌 API 주소를
 * 꺼내고 ②Bearer 토큰을 붙여 요청하고 ③응답을 **런타임 검증**해 구분 가능한 결과값으로 바꾸는 것뿐이다.
 * 어떤 버튼을 보일지는 서버가 준 `allowed_actions`·`fields`·`can_review`가 정하고, 낡은 화면인지는
 * 서버가 `expected_*`로 판정한다(409). **화면에서 버튼을 숨기는 것은 보안이 아니다** — 권한은 서버가
 * 모든 쓰기에서 DB 접근 전에 검사한다(`schema/cms_access.py`).
 *
 * 구조: 네트워크 호출(fetch)은 아래 `request()` **한 곳**뿐이다. 읽기·쓰기가 모두 이 함수를 지나므로
 * 토큰 부착·타임아웃·자격증명 모드·예외 타입명 기록이 호출마다 갈라질 수 없다
 * (`tests/infra/test_webapp_admin_cms_governance.py`가 동결).
 *
 * 응답 검증: 타입 단언으로 서버를 믿지 않는다. 모양이 틀리면 `malformed`다 — 틀린 응답을 정상 화면으로
 * 그리면 편집자가 "없는 값"을 보고 저장하게 된다.
 */

import { apiBaseUrl } from "./adminApi";

/** 10초 타임아웃 — 느린 백엔드에 무한 대기하지 않는다(CLAUDE.md). */
const REQUEST_TIMEOUT_MS = 10_000;

const CMS_BASE = "/v1/admin/cms";

// ── 응답 타입 ────────────────────────────────────────────────────────────

export type CmsFieldKind = "text" | "longtext" | "int" | "float" | "date" | "choice";

export interface CmsFieldMeta {
  name: string;
  label_ko: string;
  kind: CmsFieldKind;
  max_length: number | null;
  choices: string[] | null;
  nullable: boolean;
}

export interface CmsResourceMeta {
  key: string;
  label_ko: string;
  /** 이 리소스를 소유한 콘솔 모듈의 화면 경로(서버가 레지스트리에서 파생). */
  route: string;
  /** 목록 행·상세 경로가 가리키는 기본키 컬럼 이름. */
  pk_column: string;
  /** 변경이력 조회 종류. 읽기 전용 리소스는 쓰기가 없어 null. */
  audit_type: string | null;
  list_columns: string[];
  detail_columns: string[];
  fields: CmsFieldMeta[];
  reviewable: boolean;
  read_only: boolean;
}

export interface CmsResources {
  resources: CmsResourceMeta[];
  capabilities: string[];
}

export interface CmsList {
  resource: string;
  columns: string[];
  items: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

export interface CmsDetail {
  resource: string;
  pk: string;
  values: Record<string, unknown>;
  /** 호출자가 **지금** 고칠 수 있는 필드(편집 권한이 없으면 빈 배열). */
  fields: CmsFieldMeta[];
  can_review: boolean;
  edit_blocked_reason: string | null;
}

export interface CmsEdit {
  changed: string[];
  /** 서버가 안전한 방향으로 되돌린 검수 표지. */
  server_reset: string[];
  detail: CmsDetail;
}

export interface CmsReview {
  changed: boolean;
  review_status: string;
}

export interface CmsConceptRow {
  concept_id: string;
  code: string;
  name_ko: string;
  level: string;
  has_published_version: boolean;
}

export interface CmsConceptList {
  items: CmsConceptRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface CmsEdgeRow {
  other_concept_id: string;
  other_code: string;
  other_name_ko: string;
  edge_type: string;
}

export interface CmsConceptDetail {
  concept_id: string;
  code: string;
  live: Record<string, unknown>;
  published_version_id: string | null;
  latest_version_no: number | null;
  incoming: CmsEdgeRow[];
  outgoing: CmsEdgeRow[];
  can_edit: boolean;
}

export interface CmsVersionSummary {
  version_id: string;
  concept_code: string;
  version_no: number;
  status: string;
  created_by: string | null;
  reviewed_by: string | null;
  approved_by: string | null;
  content_hash: string | null;
  change_reason: string | null;
  created_at: string | null;
  published_at: string | null;
  /** 전이표가 허용하고 **호출자 권한으로 실행할 수 있는** 전이. 버튼은 이것만 그린다. */
  allowed_actions: string[];
}

export interface CmsGateRecord {
  gate: string;
  action: string;
  judged_by: string;
  judged_at: string;
  checks: string[];
  content_hash: string;
}

export interface CmsVersionDetail {
  summary: CmsVersionSummary;
  payload: Record<string, unknown>;
  gate_records: CmsGateRecord[];
}

export interface CmsRollbackDone {
  concept_code: string;
  rolled_back_version_id: string;
  restored_version_id: string;
}

export interface CmsAuditRow {
  action: string | null;
  actor_user_id: string;
  occurred_at: string | null;
}

export interface CmsAudit {
  resource_type: string;
  resource_key: string;
  items: CmsAuditRow[];
  note: string;
}

// ── 실패 유니온 ──────────────────────────────────────────────────────────

/** 서버 오류 본문 `{detail:{code,message,...}}`(또는 FastAPI 기본형)에서 읽은 사유. */
export interface CmsProblem {
  /** 안정 식별자. 문구가 아니라 이것으로 분기한다. 서버가 안 줬으면 빈 문자열. */
  code: string;
  message: string;
  /** 거부된 입력 필드. */
  field: string | null;
  /** 게이트 실패 사유·알 수 없는 스킬 id 등 부가 목록. */
  details: string[];
  /** 409 `stale_status`가 알려 주는 서버의 현재 상태. */
  currentStatus: string | null;
}

/** 호출 종류와 무관한 실패. 사유마다 운영자가 해야 할 행동이 달라 합치지 않는다. */
export type CmsFailure =
  | { kind: "no-api-base" }
  | { kind: "unauthenticated" }
  | { kind: "forbidden"; problem: CmsProblem }
  | { kind: "not-found" }
  | { kind: "conflict"; problem: CmsProblem }
  | { kind: "validation"; problem: CmsProblem }
  | { kind: "http-error"; status: number }
  | { kind: "malformed"; reason: string }
  | { kind: "unreachable"; reason: string };

export type CmsResult<T> = { kind: "ok"; data: T } | CmsFailure;

// ── 런타임 검증 도구 ─────────────────────────────────────────────────────
//
// 파서는 `{ v }`(성공) 또는 `null`(계약 위반)을 돌려준다. 값 자체가 null일 수 있어(`strOrNull`)
// 값을 그대로 돌려주면 "성공한 null"과 "실패"가 같아진다 — 그래서 한 겹 감싼다.

type Parsed<T> = { v: T } | null;
type Parser<T> = (raw: unknown) => Parsed<T>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const pStr: Parser<string> = (raw) => (typeof raw === "string" ? { v: raw } : null);
const pStrOrNull: Parser<string | null> = (raw) =>
  raw === null || typeof raw === "string" ? { v: raw } : null;
const pBool: Parser<boolean> = (raw) => (typeof raw === "boolean" ? { v: raw } : null);
const pInt: Parser<number> = (raw) =>
  typeof raw === "number" && Number.isInteger(raw) ? { v: raw } : null;
const pIntOrNull: Parser<number | null> = (raw) =>
  raw === null || (typeof raw === "number" && Number.isInteger(raw)) ? { v: raw } : null;
const pRecord: Parser<Record<string, unknown>> = (raw) => (isRecord(raw) ? { v: raw } : null);

function pArray<T>(item: Parser<T>): Parser<T[]> {
  return (raw) => {
    if (!Array.isArray(raw)) return null;
    const out: T[] = [];
    for (const element of raw) {
      const parsed = item(element);
      // 모르는 원소를 조용히 버리면 "버튼이 왜 없지"가 되므로 계약 위반으로 올린다.
      if (parsed === null) return null;
      out.push(parsed.v);
    }
    return { v: out };
  };
}

function pOneOf<T extends string>(allowed: readonly T[]): Parser<T> {
  return (raw) =>
    typeof raw === "string" && (allowed as readonly string[]).includes(raw) ? { v: raw as T } : null;
}

function pObject<T extends object>(shape: { [K in keyof T]-?: Parser<T[K]> }): Parser<T> {
  return (raw) => {
    if (!isRecord(raw)) return null;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(shape)) {
      const parsed = (shape as Record<string, Parser<unknown>>)[key](raw[key]);
      if (parsed === null) return null;
      out[key] = parsed.v;
    }
    return { v: out as T };
  };
}

const pFieldMeta = pObject<CmsFieldMeta>({
  name: pStr,
  label_ko: pStr,
  kind: pOneOf(["text", "longtext", "int", "float", "date", "choice"] as const),
  max_length: pIntOrNull,
  choices: (raw) => (raw === null ? { v: null } : pArray(pStr)(raw)),
  nullable: pBool,
});

const pResourceMeta = pObject<CmsResourceMeta>({
  key: pStr,
  label_ko: pStr,
  route: pStr,
  pk_column: pStr,
  audit_type: pStrOrNull,
  list_columns: pArray(pStr),
  detail_columns: pArray(pStr),
  fields: pArray(pFieldMeta),
  reviewable: pBool,
  read_only: pBool,
});

const pResources = pObject<CmsResources>({
  resources: pArray(pResourceMeta),
  capabilities: pArray(pStr),
});

const pList = pObject<CmsList>({
  resource: pStr,
  columns: pArray(pStr),
  items: pArray(pRecord),
  total: pInt,
  limit: pInt,
  offset: pInt,
});

const pDetail = pObject<CmsDetail>({
  resource: pStr,
  pk: pStr,
  values: pRecord,
  fields: pArray(pFieldMeta),
  can_review: pBool,
  edit_blocked_reason: pStrOrNull,
});

const pEdit = pObject<CmsEdit>({
  changed: pArray(pStr),
  server_reset: pArray(pStr),
  detail: pDetail,
});

const pReview = pObject<CmsReview>({ changed: pBool, review_status: pStr });

const pConceptRow = pObject<CmsConceptRow>({
  concept_id: pStr,
  code: pStr,
  name_ko: pStr,
  level: pStr,
  has_published_version: pBool,
});

const pConceptList = pObject<CmsConceptList>({
  items: pArray(pConceptRow),
  total: pInt,
  limit: pInt,
  offset: pInt,
});

const pEdgeRow = pObject<CmsEdgeRow>({
  other_concept_id: pStr,
  other_code: pStr,
  other_name_ko: pStr,
  edge_type: pStr,
});

const pConceptDetail = pObject<CmsConceptDetail>({
  concept_id: pStr,
  code: pStr,
  live: pRecord,
  published_version_id: pStrOrNull,
  latest_version_no: pIntOrNull,
  incoming: pArray(pEdgeRow),
  outgoing: pArray(pEdgeRow),
  can_edit: pBool,
});

const pVersionSummary = pObject<CmsVersionSummary>({
  version_id: pStr,
  concept_code: pStr,
  version_no: pInt,
  status: pStr,
  created_by: pStrOrNull,
  reviewed_by: pStrOrNull,
  approved_by: pStrOrNull,
  content_hash: pStrOrNull,
  change_reason: pStrOrNull,
  created_at: pStrOrNull,
  published_at: pStrOrNull,
  allowed_actions: pArray(pStr),
});

const pGateRecord = pObject<CmsGateRecord>({
  gate: pStr,
  action: pStr,
  judged_by: pStr,
  judged_at: pStr,
  checks: pArray(pStr),
  content_hash: pStr,
});

const pVersionDetail = pObject<CmsVersionDetail>({
  summary: pVersionSummary,
  payload: pRecord,
  gate_records: pArray(pGateRecord),
});

const pRollbackDone = pObject<CmsRollbackDone>({
  concept_code: pStr,
  rolled_back_version_id: pStr,
  restored_version_id: pStr,
});

const pAuditRow = pObject<CmsAuditRow>({
  action: pStrOrNull,
  actor_user_id: pStr,
  occurred_at: pStrOrNull,
});

const pAudit = pObject<CmsAudit>({
  resource_type: pStr,
  resource_key: pStr,
  items: pArray(pAuditRow),
  note: pStr,
});

// ── 오류 본문 해석 ───────────────────────────────────────────────────────

const EMPTY_PROBLEM: CmsProblem = { code: "", message: "", field: null, details: [], currentStatus: null };

/**
 * 오류 본문 → 사유. 서버는 `{detail:{code,message,...}}`를 주지만 모듈 가드의 403은 `{detail:"문자열"}`,
 * FastAPI 기본 422는 `{detail:[{loc,msg}]}`다 — 세 모양을 모두 읽고, 못 읽으면 빈 사유를 돌려준다.
 */
function readProblem(payload: unknown): CmsProblem {
  if (!isRecord(payload)) return EMPTY_PROBLEM;
  const detail = payload.detail;
  if (typeof detail === "string") return { ...EMPTY_PROBLEM, message: detail };
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    if (isRecord(first) && typeof first.msg === "string") {
      const loc = Array.isArray(first.loc) ? first.loc.filter((p) => typeof p === "string").join(".") : "";
      return { ...EMPTY_PROBLEM, message: first.msg, field: loc.length > 0 ? loc : null };
    }
    return EMPTY_PROBLEM;
  }
  if (!isRecord(detail)) return EMPTY_PROBLEM;
  const details: string[] = [];
  for (const key of ["failures", "unknown"]) {
    const value = detail[key];
    if (Array.isArray(value)) {
      for (const item of value) if (typeof item === "string") details.push(item);
    }
  }
  return {
    code: typeof detail.code === "string" ? detail.code : "",
    message: typeof detail.message === "string" ? detail.message : "",
    field: typeof detail.field === "string" ? detail.field : null,
    details,
    currentStatus: typeof detail.current_status === "string" ? detail.current_status : null,
  };
}

// ── 단 하나의 fetch ──────────────────────────────────────────────────────

type RawResult =
  | { tag: "failure"; failure: CmsFailure }
  | { tag: "response"; status: number; ok: boolean; payload: unknown; parsed: boolean };

/**
 * 모든 호출이 지나는 유일한 `fetch` 지점.
 *
 * 쿠키를 주고받지 않는다(`credentials:"omit"`) — Bearer 헤더만 쓰며, 자격증명 모드를 켜면 서버의 CORS
 * 설정과 어긋나 조용히 차단된다. 예외는 **타입명**만 남긴다(침묵 실패 금지 · 토큰·본문 값은 기록하지
 * 않는다).
 */
async function request(
  token: string,
  method: "GET" | "POST" | "PATCH",
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

/** 상태코드 → 실패. 2xx면 null. */
function statusFailure(raw: Extract<RawResult, { tag: "response" }>): CmsFailure | null {
  if (raw.ok) return null;
  switch (raw.status) {
    case 401:
      return { kind: "unauthenticated" };
    case 403:
      return { kind: "forbidden", problem: readProblem(raw.payload) };
    case 404:
      return { kind: "not-found" };
    case 409:
      return { kind: "conflict", problem: readProblem(raw.payload) };
    case 422:
      return { kind: "validation", problem: readProblem(raw.payload) };
    default:
      return { kind: "http-error", status: raw.status };
  }
}

/** 요청 1회 + 상태 판정 + 응답 검증. `what`은 계약 위반 사유에 넣을 호출 이름이다. */
async function run<T>(
  token: string,
  method: "GET" | "POST" | "PATCH",
  path: string,
  parser: Parser<T>,
  what: string,
  body?: unknown,
): Promise<CmsResult<T>> {
  const raw = await request(token, method, path, body);
  if (raw.tag === "failure") return raw.failure;
  const failure = statusFailure(raw);
  if (failure !== null) return failure;
  if (!raw.parsed) return { kind: "malformed", reason: what + ": JSON 파싱 실패" };
  const data = parser(raw.payload);
  if (data === null) return { kind: "malformed", reason: what + ": 응답 구조가 계약과 다름" };
  return { kind: "ok", data: data.v };
}

function segment(value: string): string {
  return encodeURIComponent(value);
}

function pageQuery(q: string, limit: number, offset: number): string {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const trimmed = q.trim();
  if (trimmed.length > 0) query.set("q", trimmed);
  return "?" + query.toString();
}

// ── 리소스(개념 외) ──────────────────────────────────────────────────────

/** 리소스 선언 — 목록·폼을 서버 선언에서 그린다(화면이 규칙을 복제하지 않는다). */
export function fetchCmsResources(token: string): Promise<CmsResult<CmsResources>> {
  return run(token, "GET", CMS_BASE + "/resources", pResources, "리소스 선언");
}

export function fetchCmsList(
  token: string,
  resource: string,
  q: string,
  limit: number,
  offset: number,
): Promise<CmsResult<CmsList>> {
  return run(token, "GET", CMS_BASE + "/" + segment(resource) + pageQuery(q, limit, offset), pList, "목록");
}

export function fetchCmsDetail(
  token: string,
  resource: string,
  pk: string,
): Promise<CmsResult<CmsDetail>> {
  return run(token, "GET", CMS_BASE + "/" + segment(resource) + "/items/" + segment(pk), pDetail, "상세");
}

/** 허용 필드 수정. 상태·발행 컬럼은 서버가 거부한다 — 화면은 서버가 준 `fields`만 보낸다. */
export function patchCmsItem(
  token: string,
  resource: string,
  pk: string,
  changes: Record<string, unknown>,
): Promise<CmsResult<CmsEdit>> {
  return run(
    token,
    "PATCH",
    CMS_BASE + "/" + segment(resource) + "/items/" + segment(pk),
    pEdit,
    "수정",
    { changes },
  );
}

/** 텍스트 검수 표지 올리기(`reviewed`)·내리기(`needs_review`). 검수 권한은 서버가 검사한다. */
export function reviewCmsItem(
  token: string,
  resource: string,
  pk: string,
  decision: "reviewed" | "needs_review",
): Promise<CmsResult<CmsReview>> {
  return run(
    token,
    "POST",
    CMS_BASE + "/" + segment(resource) + "/items/" + segment(pk) + "/review",
    pReview,
    "검수",
    { decision },
  );
}

// ── 개념 · 버전 워크플로우 ───────────────────────────────────────────────

export function fetchCmsConcepts(
  token: string,
  q: string,
  limit: number,
  offset: number,
): Promise<CmsResult<CmsConceptList>> {
  return run(token, "GET", CMS_BASE + "/concepts" + pageQuery(q, limit, offset), pConceptList, "개념 목록");
}

export function fetchCmsConcept(token: string, conceptId: string): Promise<CmsResult<CmsConceptDetail>> {
  return run(token, "GET", CMS_BASE + "/concepts/" + segment(conceptId), pConceptDetail, "개념 상세");
}

/** 수정은 항상 새 DRAFT 판이다(살아있는 개념 행을 직접 고치지 않는다). */
export function createCmsDraft(
  token: string,
  conceptId: string,
  changes: Record<string, unknown>,
  reason: string | null,
): Promise<CmsResult<CmsVersionSummary>> {
  const body: { changes: Record<string, unknown>; reason?: string } = { changes };
  if (reason !== null) body.reason = reason;
  return run(
    token,
    "POST",
    CMS_BASE + "/concepts/" + segment(conceptId) + "/drafts",
    pVersionSummary,
    "초안 생성",
    body,
  );
}

export function fetchCmsVersions(
  token: string,
  conceptId: string,
): Promise<CmsResult<CmsVersionSummary[]>> {
  return run(
    token,
    "GET",
    CMS_BASE + "/concepts/" + segment(conceptId) + "/versions",
    pArray(pVersionSummary),
    "판 목록",
  );
}

export function fetchCmsVersion(token: string, versionId: string): Promise<CmsResult<CmsVersionDetail>> {
  return run(token, "GET", CMS_BASE + "/versions/" + segment(versionId), pVersionDetail, "판 상세");
}

/**
 * 판 전이(제출·검토·승인·발행·폐기·은퇴). `expectedStatus`는 사용자가 화면에서 **본 상태 그대로**
 * 보낸다 — 낡았는지의 판정(409 `stale_status`)은 서버가 한다. 클라가 "지금도 이 상태겠지"를 추정해
 * 고치지 않는다.
 */
export function transitionCmsVersion(
  token: string,
  versionId: string,
  action: string,
  expectedStatus: string,
): Promise<CmsResult<CmsVersionSummary>> {
  return run(
    token,
    "POST",
    CMS_BASE + "/versions/" + segment(versionId) + "/transitions",
    pVersionSummary,
    "전이",
    { action, expected_status: expectedStatus },
  );
}

/** 롤백. `expectedPublishedVersionId`는 화면이 본 현재 발행본 — 그사이 바뀌었으면 409. */
export function rollbackCmsConcept(
  token: string,
  conceptId: string,
  expectedPublishedVersionId: string,
): Promise<CmsResult<CmsRollbackDone>> {
  return run(
    token,
    "POST",
    CMS_BASE + "/concepts/" + segment(conceptId) + "/rollback",
    pRollbackDone,
    "롤백",
    { expected_published_version_id: expectedPublishedVersionId },
  );
}

// ── 변경이력(감사) ───────────────────────────────────────────────────────

/** 제자리 편집 리소스·판의 변경이력 — 누가·언제·무슨 동작(diff는 없다). */
export function fetchCmsAudit(
  token: string,
  resourceType: string,
  resourceKey: string,
): Promise<CmsResult<CmsAudit>> {
  const query = new URLSearchParams({ resource_type: resourceType, resource_key: resourceKey });
  return run(token, "GET", CMS_BASE + "/audit?" + query.toString(), pAudit, "변경이력");
}
