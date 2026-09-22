/**
 * Admin BFF 클라이언트 — 백오피스 셸이 백엔드와 말하는 **유일한 자리**.
 *
 * 경계 (04 §2 원칙1·§3)
 * --------------------
 * 여기에는 수학 로직도, 권한 판정도, 집계도 없다. 이 파일이 하는 일은 ①빌드에 박힌 API
 * 주소를 꺼내고 ②Bearer 토큰을 붙여 GET 한 번 하고 ③응답을 **구분 가능한 결과값**으로
 * 바꾸는 것뿐이다. 판정(누가 무엇을 보는가)은 전부 서버가 한다 — 프런트는 코어를 직접
 * 호출하지 않고 항상 BFF를 경유한다(04 §3 "프런트는 코어를 직접 호출하지 않는다").
 *
 * 왜 결과를 유니온으로 돌려주는가 (04 §2 원칙6 · CLAUDE.md "측정 실패 ≠ 0건")
 * -------------------------------------------------------------------------
 * 메뉴 호출은 **여섯 가지 서로 다른 이유**로 비어 보일 수 있다: API 주소 미주입 · 토큰 없음
 * (401) · 데모/무권한(403) · 권한은 되는데 볼 모듈이 0건 · 서버 오류 · **CORS 차단**.
 * 이걸 전부 "빈 메뉴"로 접으면 운영자가 보는 화면은 "기능이 없는 콘솔"이 되고, 그것은
 * 위장이다. 그래서 호출부가 각각을 다르게 말할 수 있도록 태그된 유니온으로 되돌린다.
 *
 * CORS 차단이 특히 중요하다 — 브라우저는 차단된 cross-origin 응답을 **자바스크립트에
 * 넘기지 않으므로** `fetch`가 상태 코드 없이 `TypeError`로 던진다. 즉 서버 로그에는
 * 정상 200이 찍히는데 화면만 죽는다. `unreachable`이 그 자리를 잡고, 화면이 해결책
 * (`WHYMATH_CORS_ALLOWED_ORIGINS`)까지 말한다.
 */

/** 이 셸이 호출하는 단 하나의 엔드포인트. 04 §2 원칙7 — 앱 로드 시 **1회**. */
export const ADMIN_MENU_PATH = "/v1/admin/menu";

/** 느린 백엔드에 무한 대기하지 않는다(CLAUDE.md — 외부 호출에는 전부 타임아웃). */
const REQUEST_TIMEOUT_MS = 10_000;

/** 레지스트리 `AdminModuleStatus`의 3값. 라벨·색 같은 *표현*은 렌더 쪽이 정한다. */
export type AdminModuleStatus = "live" | "partial" | "planned";

export interface AdminMenuItem {
  id: string;
  label_ko: string;
  route: string;
  status: AdminModuleStatus;
}

export interface AdminMenuSection {
  key: string;
  label_ko: string;
  items: AdminMenuItem[];
}

/**
 * 메뉴 호출의 결과. **`ok`와 `empty`가 갈라져 있는 것이 이 타입의 핵심**이다 —
 * 200을 받았는데 섹션이 0건이면 그것은 "모듈이 없다"가 아니라 "이 계정의 역할로는 볼 수
 * 있는 모듈이 0건"이라는 뜻이고(서버는 권한 부족에 403이 아니라 빈 메뉴를 준다 — 04 §2
 * 원칙7), 그 둘은 운영자가 해야 할 행동이 다르다.
 */
export type AdminMenuResult =
  | { kind: "ok"; sections: AdminMenuSection[] }
  | { kind: "empty" }
  | { kind: "no-api-base" }
  | { kind: "unauthenticated" }
  | { kind: "forbidden"; detail: string }
  | { kind: "http-error"; status: number }
  | { kind: "malformed"; reason: string }
  | { kind: "unreachable"; reason: string };

/**
 * 빌드에 박힌 백엔드 주소. 비면 `null` — **상대 경로로 조용히 폴백하지 않는다**.
 *
 * 정적 export라 이 값은 빌드 타임에 인라인된다. 폴백을 허용하면 주소를 안 넣은 빌드가
 * 자기 자신(정적 호스트)에게 `/v1/admin/menu`를 요청해 404를 받고, 화면에는 "메뉴 없음"이
 * 뜬다 — 설정 누락이 기능 부재로 위장되는 전형이다.
 */
export function apiBaseUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_WHYMATH_API_BASE_URL;
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseItem(raw: unknown): AdminMenuItem | null {
  if (!isRecord(raw)) return null;
  const { id, label_ko: labelKo, route, status } = raw;
  if (typeof id !== "string" || typeof labelKo !== "string" || typeof route !== "string") {
    return null;
  }
  if (status !== "live" && status !== "partial" && status !== "planned") return null;
  return { id, label_ko: labelKo, route, status };
}

function parseSections(raw: unknown): AdminMenuSection[] | null {
  if (!isRecord(raw) || !Array.isArray(raw.sections)) return null;
  const sections: AdminMenuSection[] = [];
  for (const rawSection of raw.sections) {
    if (!isRecord(rawSection)) return null;
    const { key, label_ko: labelKo, items } = rawSection;
    if (typeof key !== "string" || typeof labelKo !== "string" || !Array.isArray(items)) {
      return null;
    }
    const parsed: AdminMenuItem[] = [];
    for (const rawItem of items) {
      const item = parseItem(rawItem);
      if (item === null) return null;
      parsed.push(item);
    }
    sections.push({ key, label_ko: labelKo, items: parsed });
  }
  return sections;
}

/**
 * 좌측 내비의 원천을 1회 가져온다. 섹션 순서·라벨까지 **서버가 준 그대로** 쓴다 —
 * 프런트가 순서 배열을 들고 있으면 그것이 곧 하드코딩 nav의 재발이다(04 §2 원칙7).
 */
export async function fetchAdminMenu(token: string): Promise<AdminMenuResult> {
  const base = apiBaseUrl();
  if (base === null) return { kind: "no-api-base" };

  let response: Response;
  try {
    response = await fetch(base + ADMIN_MENU_PATH, {
      method: "GET",
      headers: { Authorization: "Bearer " + token, Accept: "application/json" },
      // 쿠키를 주고받지 않는다 — 이 백엔드는 Bearer 토큰을 헤더로 받고(`cors_allow_credentials`
      // 기본 false), 자격증명 모드를 켜면 서버의 CORS 설정과 어긋나 조용히 차단된다.
      credentials: "omit",
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    // CORS 차단·DNS·연결 거부·타임아웃이 전부 여기로 온다. 예외 *타입명*을 남긴다
    // (CLAUDE.md 침묵 실패 금지 — 무타입 경고는 8개의 다른 실패를 같은 글자로 만든다).
    const name = error instanceof Error ? error.name : typeof error;
    return { kind: "unreachable", reason: name };
  }

  if (response.status === 401) return { kind: "unauthenticated" };
  if (response.status === 403) {
    let detail = "";
    try {
      const body: unknown = await response.json();
      if (isRecord(body) && typeof body.detail === "string") detail = body.detail;
    } catch {
      detail = "";
    }
    return { kind: "forbidden", detail };
  }
  if (!response.ok) return { kind: "http-error", status: response.status };

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    const name = error instanceof Error ? error.name : typeof error;
    return { kind: "malformed", reason: "JSON 파싱 실패(" + name + ")" };
  }

  const sections = parseSections(payload);
  if (sections === null) return { kind: "malformed", reason: "응답 구조가 계약과 다름" };
  if (sections.length === 0) return { kind: "empty" };
  return { kind: "ok", sections };
}
