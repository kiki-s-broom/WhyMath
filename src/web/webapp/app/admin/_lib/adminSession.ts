/**
 * 운영자 토큰 보관 — 백오피스 셸의 자격증명 취급 규칙(04 §4).
 *
 * 무엇을 보관하는가
 * ----------------
 * 실 신원 로그인(카카오·네이버 OAuth — `POST /v1/auth/{provider}/callback`)으로 발급된
 * **액세스 토큰**뿐이다. 셸은 토큰을 *만들지 않는다* — 발급은 기존 인증 경로가 하고, 여기서는
 * 운영자가 가져온 것을 이 탭에서만 들고 있는다.
 *
 * 왜 탭 수명 저장소인가
 * --------------------
 * `sessionStorage`는 탭을 닫으면 사라지고 다른 탭·창과 공유되지 않는다. 탭을 닫아도 남는
 * 브라우저 저장소에 두면 공용 운영 PC에서 다음 사람이 그대로 이어 받고, 쿠키에 두면 CSRF
 * 표면이 생긴다(이 백엔드는 쿠키를 쓰지 않는다 — `cors_allow_credentials` 기본 false).
 * 관리 콘솔은 내부망 전용이지만(04 §5) 그것은 네트워크 경계이지 단말 경계가 아니다.
 *
 * 정직한 한계 — 셸은 데모 토큰을 **식별할 수 없다**
 * ------------------------------------------------
 * 04 §4는 데모 토큰(`demo_auth`)을 금지하지만, 그 판정은 클라가 할 수 있는 일이 아니다:
 * 이 백엔드의 JWT 클레임은 `sub`·`typ`·`iat`·`exp`뿐이고 발급 출처 표식(`iss`·provider·`amr`)이
 * 없다(`api/admin_module_registry.is_demo_account` docstring의 실측). 그래서 셸은 토큰을
 * 해석하지 않고 **서버 판정을 그대로 보여 준다** — 데모 계정이면 서버가 403을 내고 화면은 그
 * 사유를 감추지 않는다. 클라에서 흉내 낸 검사를 붙이면 "막고 있다"는 거짓 안심만 늘어난다.
 */

/** 탭 단위 키. 다른 WhyMath 웹 자산과 섞이지 않도록 접두를 붙인다. */
const TOKEN_KEY = "wm.admin.operator_token";

/**
 * 저장소 접근은 **항상** 예외를 낼 수 있다(프라이빗 모드·사이트 데이터 차단·iframe 격리).
 * 삼키되 조용하지 않게: 실패는 `null`/`false`로 *구분되어* 되돌아가고, 호출부가 화면에 말한다.
 */
function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readOperatorToken(): string | null {
  const store = storage();
  if (store === null) return null;
  try {
    const value = store.getItem(TOKEN_KEY);
    return value !== null && value.trim().length > 0 ? value : null;
  } catch {
    return null;
  }
}

/** 저장 성공 여부를 되돌린다 — 실패를 성공으로 위장하면 다음 새로고침에 토큰이 사라진다. */
export function writeOperatorToken(token: string): boolean {
  const store = storage();
  if (store === null) return false;
  try {
    store.setItem(TOKEN_KEY, token.trim());
    return true;
  } catch {
    return false;
  }
}

export function clearOperatorToken(): void {
  const store = storage();
  if (store === null) return;
  try {
    store.removeItem(TOKEN_KEY);
  } catch {
    // 지우지 못했으면 탭을 닫는 것이 유일한 보장이다 — 화면의 로그아웃 안내가 그것을 말한다.
  }
}
